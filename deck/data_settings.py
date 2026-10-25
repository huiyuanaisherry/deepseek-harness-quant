"""Restricted Tushare configuration and bounded, pinned public-network checks."""
import datetime
import getpass
import hashlib
import http.client
import ipaddress
import json
import os
import queue
from pathlib import Path
import socket
import ssl
import stat
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

import yaml

try:
    from .model_settings import SettingsError
except ImportError:
    from model_settings import SettingsError

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENDPOINT = 'https://api.tushare.pro'
MAX_CONFIG = 1024 * 1024
MAX_RESPONSE = 256 * 1024
_CONFIG_LOCK = threading.RLock()
_DNS_SLOTS = threading.BoundedSemaphore(4)
_GATES = {}
_GATE_LOCK = threading.Lock()


def _url(url):
    try:
        if not isinstance(url, str) or not 0 < len(url) <= 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url) or '\\' in url:
            raise ValueError()
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None or '?' in url or '#' in url:
            raise ValueError()
        parsed.hostname.encode('idna')
        parsed.port
        return parsed
    except (ValueError, TypeError, UnicodeError):
        raise SettingsError('INVALID_ENDPOINT', 400) from None


def _resolve_bounded(host, port, resolver, timeout):
    # A hung system resolver cannot be cancelled. Bound both waiting time and the
    # process-wide number of daemon workers; never join an unresponsive resolver.
    if not _DNS_SLOTS.acquire(blocking=False):
        raise SettingsError('NETWORK', 502)
    result = queue.Queue(maxsize=1)
    def run():
        try:
            result.put((True, resolver(host, port, type=socket.SOCK_STREAM)))
        except Exception:
            result.put((False, None))
        finally:
            _DNS_SLOTS.release()
    threading.Thread(target=run, daemon=True, name='tushare-dns').start()
    try:
        ok, answers = result.get(timeout=timeout)
    except queue.Empty:
        raise SettingsError('NETWORK', 502) from None
    if not ok:
        raise SettingsError('NETWORK', 502)
    return answers


def resolve_endpoint(url, resolver=None, timeout=3):
    parsed = _url(url)
    try:
        answers = _resolve_bounded(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), resolver or socket.getaddrinfo, timeout)
        ips = [answer[4][0] for answer in answers]
        if not ips or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in ips):
            raise ValueError()
        # Literal hosts must also be public even with a custom DNS resolver.
        try:
            literal = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            literal = None
        if literal is not None and (not literal.is_global or literal.is_multicast):
            raise ValueError()
        return ips[0]
    except (OSError, ValueError, TypeError, IndexError):
        raise SettingsError('INVALID_ENDPOINT', 400) from None


class _SocketDeadline:
    """Abort the live socket even while HTTP headers or chunk framing trickle in."""
    def __init__(self, timeout):
        self.expires = time.monotonic() + timeout
        self.expired = threading.Event()
        self.lock = threading.Lock()
        self.sock = None
        self.timer = threading.Timer(timeout, self.abort)
        self.timer.daemon = True

    @staticmethod
    def _close(sock):
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def abort(self):
        with self.lock:
            self.expired.set()
            self._close(self.sock)

    def register(self, sock):
        with self.lock:
            self.sock = sock
            if self.expired.is_set() or time.monotonic() >= self.expires:
                self.expired.set()
                self._close(sock)
                raise TimeoutError()
        return sock


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self.ip = ip
        self.deadline = None

    def connect(self):
        sock = socket.create_connection((self.ip, self.port), self.timeout)
        self.sock = self.deadline.register(sock) if self.deadline else sock


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self.ip = ip
        self.deadline = None

    def connect(self):
        raw = socket.create_connection((self.ip, self.port), self.timeout)
        self.sock = self.deadline.register(raw) if self.deadline else raw
        # Register the SSLSocket before the handshake so the absolute deadline can
        # interrupt a peer that trickles handshake records indefinitely.
        secured = self._context.wrap_socket(self.sock, server_hostname=self.host, do_handshake_on_connect=False)
        self.sock = self.deadline.register(secured) if self.deadline else secured
        self.sock.do_handshake()


class PinnedTransport:
    """Callable(endpoint, Pro payload, validated IP, timeout seconds, byte cap)."""
    def __call__(self, endpoint, payload, resolved_ip, timeout, max_response):
        parsed = _url(endpoint)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if parsed.scheme == 'https':
            connection = _PinnedHTTPSConnection(parsed.hostname, port, resolved_ip, timeout)
        else:
            connection = _PinnedHTTPConnection(parsed.hostname, port, resolved_ip, timeout)
        deadline = _SocketDeadline(timeout)
        connection.deadline = deadline
        deadline.timer.start()
        try:
            connection.request('POST', parsed.path or '/', json.dumps(payload).encode('utf-8'), {'Content-Type': 'application/json', 'Accept': 'application/json'})
            response = connection.getresponse()
            if deadline.expired.is_set():
                raise TimeoutError()
            if response.status == 429:
                raise SettingsError('RATE_LIMITED', 429)
            if response.status in (401, 403):
                raise SettingsError('CREDENTIALS' if response.status == 401 else 'PERMISSION', response.status)
            if response.status != 200:
                raise SettingsError('UPSTREAM_ERROR', 502)
            raw = response.read(max_response + 1)
            if deadline.expired.is_set():
                raise TimeoutError()
            if len(raw) > max_response:
                raise SettingsError('UPSTREAM_ERROR', 502)
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except SettingsError:
            raise
        except (OSError, http.client.HTTPException):
            raise SettingsError('NETWORK', 502) from None
        except (ValueError, UnicodeError):
            raise SettingsError('UPSTREAM_ERROR', 502) from None
        finally:
            deadline.timer.cancel()
            connection.close()


def _read(path, cap=MAX_CONFIG, missing=False):
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise OSError()
            raw = stream.read(cap + 1)
            if len(raw) > cap:
                raise OSError()
            return raw
    except FileNotFoundError:
        if missing:
            return b''
        raise SettingsError('CONFIG_READ_FAILED', 500) from None
    except OSError:
        raise SettingsError('CONFIG_READ_FAILED', 500) from None


def _configured(token):
    return isinstance(token, str) and bool(token.strip()) and not token.strip().startswith(('<', 'your-', 'YOUR_', 'your_'))


def _restrict(descriptor, path):
    """0600 on POSIX; Windows has no os.fchmod and needs an ACL instead."""
    try:
        if hasattr(os, 'fchmod'):
            os.fchmod(descriptor, 0o600)
        elif os.name == 'nt':
            subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', getpass.getuser() + ':(F)'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        raise OSError('cannot restrict configuration permissions') from None


class DataSettings:
    def __init__(self, path=None, metadata_path=None, transport=None, *, resolver=None, cooldown_seconds=3, clock=None, dns_timeout=3):
        self.path = Path(path) if path is not None else ROOT / 'config/params.yaml'
        self.metadata_path = Path(metadata_path) if metadata_path is not None else ROOT / 'config/data_sources.json'
        self.transport = transport or PinnedTransport()
        self.resolver = resolver
        self.dns_timeout = dns_timeout
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock or time.monotonic
        with _GATE_LOCK:
            self._gate = _GATES.setdefault(os.path.abspath(self.path), {'lock': threading.Lock(), 'last': None})

    def _load(self):
        raw = _read(self.path, missing=True)
        try:
            cfg = yaml.safe_load(raw) if raw else {}
            if not isinstance(cfg, dict) or ('data' in cfg and not isinstance(cfg['data'], dict)):
                raise ValueError()
        except (ValueError, yaml.YAMLError, UnicodeError):
            raise SettingsError('CONFIG_READ_FAILED', 500) from None
        return cfg, hashlib.sha256(raw).hexdigest()

    def _metadata(self):
        try:
            value = json.loads(_read(self.metadata_path, 64 * 1024))
            if not isinstance(value, dict) or not isinstance(value.get('testSymbol'), str) or not value['testSymbol'] or len(value['testSymbol']) > 32:
                raise ValueError()
            checks = value['checks']
            if not isinstance(checks, list) or len(checks) != 3 or {v['id'] for v in checks} != {'daily', 'adj_factor', 'fina_indicator'}:
                raise ValueError()
            for check in checks:
                if check['api'] != check['id'] or not isinstance(check['label'], str) or not 0 < len(check['label']) <= 128 or not isinstance(check['fields'], str) or len(check['fields']) > 256:
                    raise ValueError()
            return value
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise SettingsError('METADATA_INVALID', 500) from None

    def _data_mode(self, data):
        # Same precedence as data/cache.py: env > data.cache_dir > data/cache.
        env = os.environ.get('LWQUANT_CACHE_DIR')
        configured = data.get('cache_dir')
        raw = env or configured or 'data/cache'
        path = Path(str(raw))
        if not path.is_absolute():
            path = self.path.parent.parent / path
        try:
            label = path.resolve().relative_to(ROOT).as_posix()
        except (ValueError, OSError):
            label = path.name or 'unknown'
        demo = 'demo' in label.lower().split('/')
        return {'kind': 'demo' if demo else 'cache', 'path': label,
                'source': 'environment' if env else ('config' if configured else 'default'),
                'note': ('当前读取演示数据（合成，仅用于界面与流程验证）；保存或验证 Tushare 配置不会切换当前数据目录。'
                         if demo else '当前读取本地缓存数据；保存或验证 Tushare 配置不会下载或切换数据。')}

    def _describe(self, cfg, revision):
        data = cfg.get('data', {})
        endpoint = data.get('tushare_api_url', DEFAULT_ENDPOINT)
        try:
            _url(endpoint)
        except SettingsError:
            endpoint = ''
        metadata = self._metadata()
        return {'ok': True, 'revision': revision, 'configured': _configured(data.get('tushare_token')), 'endpoint': endpoint, 'defaultEndpoint': DEFAULT_ENDPOINT,
                'allowInsecureHttp': data.get('tushare_allow_insecure_http') is True,
                'checks': [{'id': v['id'], 'label': v['label']} for v in metadata['checks']], 'testSymbol': metadata['testSymbol'],
                'dataMode': self._data_mode(data)}

    def describe(self):
        with _CONFIG_LOCK:
            return self._describe(*self._load())

    @staticmethod
    def _expected(body, revision, allowed):
        if not isinstance(body, dict) or set(body) - set(allowed):
            raise SettingsError('INVALID_REQUEST', 400)
        if body.get('expectedRevision') != revision:
            raise SettingsError('REVISION_CONFLICT', 409)

    def save(self, body):
        with _CONFIG_LOCK:
            cfg, revision = self._load()
            self._expected(body, revision, ('expectedRevision', 'endpoint', 'token', 'allowInsecureHttp'))
            endpoint = body.get('endpoint')
            parsed = _url(endpoint)
            if type(body.get('allowInsecureHttp', False)) is not bool:
                raise SettingsError('INVALID_REQUEST', 400)
            allow = body.get('allowInsecureHttp') is True
            if parsed.scheme == 'http' and not allow:
                raise SettingsError('INSECURE_HTTP_CONFIRMATION_REQUIRED', 400)
            token = body.get('token', '')
            if not isinstance(token, str) or len(token) > 8192 or any(ord(c) < 33 or ord(c) == 127 for c in token):
                raise SettingsError('INVALID_TOKEN', 400)
            data = cfg.setdefault('data', {})
            changed = endpoint != data.get('tushare_api_url', DEFAULT_ENDPOINT)
            # A first configuration and a new destination both need a fresh token;
            # never persist the default destination with no usable credential.
            if not _configured(token) and (changed or not _configured(data.get('tushare_token'))):
                raise SettingsError('TOKEN_REQUIRED', 400)
            if token and not _configured(token):
                raise SettingsError('INVALID_TOKEN', 400)
        if changed:
            resolve_endpoint(endpoint, self.resolver, self.dns_timeout)
        with _CONFIG_LOCK:
            if self._load()[1] != revision:
                raise SettingsError('REVISION_CONFLICT', 409)
            data.update(tushare_api_url=endpoint, tushare_allow_insecure_http=allow)
            if token:
                data['tushare_token'] = token
            # Validate metadata before committing so successful writes always return a DTO.
            self._metadata()
            temporary = None
            try:
                descriptor, temporary = tempfile.mkstemp(prefix='.params-', dir=self.path.parent)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                    _restrict(stream.fileno(), temporary)
                    yaml.safe_dump(cfg, stream, allow_unicode=True, sort_keys=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                if self._load()[1] != revision:
                    raise SettingsError('REVISION_CONFLICT', 409)
                os.replace(temporary, self.path)
                temporary = None
            except SettingsError:
                raise
            except (OSError, AttributeError, yaml.YAMLError):
                raise SettingsError('CONFIG_WRITE_FAILED', 500) from None
            finally:
                if temporary is not None:
                    os.unlink(temporary)
            return self._describe(*self._load())

    @staticmethod
    def _status(result):
        if not isinstance(result, dict):
            return 'error'
        if result.get('code') == 0:
            data = result.get('data')
            if not isinstance(data, dict) or not isinstance(data.get('items'), list):
                return 'error'
            return 'available' if data['items'] else 'empty'
        # Interpret upstream messages internally; never return them to callers.
        message = str(result.get('msg', ''))[:2048].lower()
        if any(v in message for v in ('token', '凭据', '认证', 'authentication')):
            return 'credentials'
        if any(v in message for v in ('频率', '每分钟', '限流', 'rate limit', '每小时', '每天最多')):
            return 'rate_limited'
        if any(v in message for v in ('权限', '积分', 'permission', 'not purchased')):
            return 'permission'
        return 'error'

    def verify(self, body):
        with _CONFIG_LOCK:
            cfg, revision = self._load()
            self._expected(body, revision, ('expectedRevision',))
            data = cfg.get('data', {})
            token = data.get('tushare_token')
            if not _configured(token):
                raise SettingsError('TOKEN_REQUIRED', 400)
            endpoint = data.get('tushare_api_url', DEFAULT_ENDPOINT)
            if _url(endpoint).scheme == 'http' and data.get('tushare_allow_insecure_http') is not True:
                raise SettingsError('INSECURE_HTTP_CONFIRMATION_REQUIRED', 400)
            metadata = self._metadata()
        if not self._gate['lock'].acquire(blocking=False):
            raise SettingsError('VERIFY_BUSY', 429)
        started = False
        try:
            now = self.clock()
            if self._gate['last'] is not None and now - self._gate['last'] < self.cooldown_seconds:
                raise SettingsError('VERIFY_COOLDOWN', 429)
            ip = resolve_endpoint(endpoint, self.resolver, self.dns_timeout)
            # Only an actual supplier attempt consumes the cooldown.
            started = True
            today = datetime.date.today()
            checks = []
            for check in metadata['checks']:
                with _CONFIG_LOCK:
                    if self._load()[1] != revision:
                        raise SettingsError('REVISION_CONFLICT', 409)
                params = {'ts_code': metadata['testSymbol'], 'start_date': (today - datetime.timedelta(days=550 if check['id'] == 'fina_indicator' else 14)).strftime('%Y%m%d'), 'end_date': today.strftime('%Y%m%d'), 'limit': 3}
                payload = {'api_name': check['api'], 'token': token, 'params': params, 'fields': check['fields']}
                try:
                    status = self._status(self.transport(endpoint, payload, ip, 8, MAX_RESPONSE))
                except SettingsError as error:
                    status = {'NETWORK': 'network', 'RATE_LIMITED': 'rate_limited', 'CREDENTIALS': 'credentials', 'PERMISSION': 'permission'}.get(error.code, 'error')
                except (OSError, TimeoutError):
                    status = 'network'
                except Exception:
                    status = 'error'
                checks.append({'id': check['id'], 'label': check['label'], 'status': status})
            with _CONFIG_LOCK:
                if self._load()[1] != revision:
                    raise SettingsError('REVISION_CONFLICT', 409)
            return {'ok': True, 'revision': revision, 'endpoint': endpoint, 'checks': checks}
        finally:
            if started:
                self._gate['last'] = self.clock()
            self._gate['lock'].release()
