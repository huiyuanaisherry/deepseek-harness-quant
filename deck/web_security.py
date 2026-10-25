"""Local management authentication and safe static file resolution."""
import argparse
import hmac
import json
import os
import secrets
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import unquote

def policy():
    # JSON is a YAML subset; keeping the subset needs no third-party parser.
    defaults = {'session_ttl_seconds':28800, 'login_window_seconds':300,
                'login_attempts':5, 'max_body_bytes':65536}
    path = Path(__file__).resolve().parents[1] / 'config' / 'web_security.yaml'
    if path.exists():
        values = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(values, dict):
            raise RuntimeError('Invalid web security configuration')
        for key in defaults:
            if key in values:
                value = values[key]
                if type(value) is not int or value <= 0 or value > 1048576:
                    raise RuntimeError('Invalid web security configuration')
                defaults[key] = value
    return defaults


MAX_BODY = 65536  # Absolute fallback; per-server policy is loaded below.
COOKIE = 'quant_session'


def token_path():
    home = Path(os.environ.get('DSH_HOME', str(Path(__file__).resolve().parents[1] / 'harness' / 'home')))
    return home / '.quant-web-token'


def contained_path(root, name):
    for _ in range(5):
        decoded = unquote(name, errors='strict')
        if decoded == name:
            break
        name = decoded
    if '%' in name or not name or name.startswith('/') or '\\' in name or '\x00' in name or ':' in name or '..' in name.split('/'):
        raise ValueError('Invalid file path')
    base = Path(root).resolve()
    target = (base / name).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError('Invalid file path') from None
    return target


class Security:
    def __init__(self, path=None, ttl=None):
        self.policy = policy()
        self.path = Path(path) if path is not None else token_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
        if self.path.is_symlink():
            raise RuntimeError('Management token unavailable')
        fd = os.open(str(self.path), flags, 0o600)
        try:
            if hasattr(os, 'fchmod'):
                os.fchmod(fd, 0o600)
            elif os.name == 'nt':
                import getpass
                import subprocess
                subprocess.run(['icacls', str(self.path), '/inheritance:r', '/grant:r',
                                getpass.getuser()+':(F)'], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with os.fdopen(fd, 'r+', encoding='ascii') as stream:
                self.token = stream.read(256).strip()
                if not self.token:
                    self.token = secrets.token_urlsafe(48)
                    stream.write(self.token)
                    stream.flush()
        except Exception:
            raise RuntimeError('Management token unavailable') from None
        self.public_origin = os.environ.get('QUANT_PUBLIC_ORIGIN', '').rstrip('/')
        if self.public_origin:
            from urllib.parse import urlsplit
            origin = urlsplit(self.public_origin)
            if origin.scheme not in ('http', 'https') or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
                raise RuntimeError('Invalid public origin')
        self.ttl = self.policy['session_ttl_seconds'] if ttl is None else ttl
        self.sessions = {}
        self.failures = {}
        self.lock = threading.Lock()

    def login(self, token, client):
        with self.lock:
            now = time.time()
            self.failures = {k:v for k,v in self.failures.items() if now-v[0] < self.policy['login_window_seconds']}
            start, count = self.failures.get(client, (now, 0))
            if count >= self.policy['login_attempts']:
                return None
            if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.token.encode()):
                self.failures[client] = (start, count + 1)
                return None
            self.failures.pop(client, None)
            self.sessions = {k:v for k,v in self.sessions.items() if v > now}
            if len(self.sessions) >= 1024:
                self.sessions.pop(next(iter(self.sessions)))
            session = secrets.token_urlsafe(32)
            self.sessions[session] = now + self.ttl
            return session

    def valid(self, session):
        with self.lock:
            return self.sessions.get(session, 0) > time.time()

    def logout(self, session):
        with self.lock:
            self.sessions.pop(session, None)


LOGIN_HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Quant 管理登录</title><style>body{font:16px system-ui;background:#101820;color:#eef;padding:10vh 10vw}input,button{font:inherit;padding:12px;margin:8px 0}input{width: min(90%,480px)}p{max-width:650px}</style><h1>Quant 管理登录</h1><p>在服务端本地终端读取管理令牌： <code>python -m deck.web_security --show-token</code></p><form><label>管理令牌<br><input type="password" autocomplete="off" required></label><br><button>登录</button></form><p id="message" role="status"></p><script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();let input=document.querySelector('input');try{let r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json','X-Quant-Request':'1'},body:JSON.stringify({token:input.value})});input.value='';if(r.ok)location.href='/';else document.getElementById('message').textContent='登录失败，请检查令牌或五分钟后重试。'}catch(e){input.value='';document.getElementById('message').textContent='连接失败，请重试。'}};</script></html>'''.encode('utf-8')


class SecurityMixin:
    def log_message(self, fmt, *args):
        # Request targets can carry secrets; never log them.
        pass

    @property
    def security(self):
        with _INIT_LOCK:
            if not hasattr(self.server, 'security'):
                self.server.security = Security()
        return self.server.security

    def _session(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            return cookie[COOKIE].value if COOKIE in cookie else ''
        except Exception:
            return ''

    def _error(self, code, status):
        return self._send_json({'ok':False, 'error':code.replace('_',' ').capitalize(), 'code':code}, status)

    def _read_json(self):
        if hasattr(self, '_body_json'):
            return self._body_json
        raise ValueError('JSON body unavailable')

    def _gate(self, write=False):
        path = self.path.split('?', 1)[0]
        if not write and path == '/login':
            self._send(200, LOGIN_HTML, 'text/html; charset=utf-8')
            return False
        authenticated = self.security.valid(self._session())
        if not write and path == '/api/auth/status':
            self._send_json({'ok':True,'authenticated':authenticated})
            return False
        if path != '/api/auth/login' and not authenticated:
            if path.startswith('/api/') or write:
                self._error('UNAUTHORIZED', 401)
            else:
                self.send_response(303)
                self.send_header('Location', '/login')
                self.send_header('Content-Length', '0')
                self.end_headers()
            return False
        if write:
            scheme = 'https' if getattr(self.server, 'https', False) else 'http'
            if self.security.public_origin:
                scheme = self.security.public_origin.split(':', 1)[0]
            host = self.headers.get('Host', '')
            if not host or self.headers.get('Origin') != (self.security.public_origin or scheme + '://' + host) or self.headers.get('X-Quant-Request') != '1':
                self._error('INVALID_ORIGIN', 403)
                return False
            try:
                n = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                n = -1
            if self.headers.get('Transfer-Encoding') or n < 0 or n > self.security.policy['max_body_bytes']:
                self.close_connection = True
                self._error('BODY_TOO_LARGE', 413)
                return False
            if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                self._error('INVALID_JSON', 415)
                return False
            try:
                self.connection.settimeout(10)
                self._body_json = json.loads(self.rfile.read(n).decode('utf-8'))
                if not isinstance(self._body_json, dict):
                    raise ValueError()
            except (ValueError, UnicodeError, OSError):
                self._error('INVALID_JSON', 400)
                return False
            if path in ('/api/auth/login', '/api/auth/logout'):
                session = self.security.login(self._body_json.get('token'), self.client_address[0]) if path.endswith('/login') else ''
                if path.endswith('/login') and session is None:
                    self._error('LOGIN_FAILED', 429)
                    return False
                if path.endswith('/logout'):
                    self.security.logout(self._session())
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(body)))
                self.send_header('Set-Cookie', COOKIE+'='+session+'; Path=/; HttpOnly; SameSite=Strict'+ ('; Secure' if scheme == 'https' else '') + ('; Max-Age=0' if not session else ''))
                self.end_headers()
                self.wfile.write(body)
                return False
        return True

_INIT_LOCK = threading.Lock()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--show-token', action='store_true', required=True)
    parser.parse_args()
    print(Security().token)


if __name__ == '__main__':
    main()
