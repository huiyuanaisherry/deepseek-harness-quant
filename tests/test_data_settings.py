import json
import os
from pathlib import Path
import socket
import threading
import time
import tempfile
import unittest
from unittest.mock import patch
import yaml
from deck.data_settings import DataSettings, PinnedTransport, resolve_endpoint
from deck.model_settings import SettingsError


def public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]


def metadata():
    return {'testSymbol': '000001.SZ', 'checks': [
        {'id': 'daily', 'label': '日线', 'api': 'daily', 'fields': 'ts_code,trade_date,close'},
        {'id': 'adj_factor', 'label': '复权', 'api': 'adj_factor', 'fields': 'ts_code,trade_date,adj_factor'},
        {'id': 'fina_indicator', 'label': '财务', 'api': 'fina_indicator', 'fields': 'ts_code,end_date,roe'}]}


class DataSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'params.yaml'
        self.path.write_text(yaml.safe_dump({'data': {'tushare_token': 'synthetic-secret', 'other': [1, 2]}, 'risk': {'x': True}}))
        self.metadata = Path(self.temp.name) / 'data_sources.json'
        self.metadata.write_text(json.dumps(metadata()))
        self.calls = []
        def transport(*args):
            self.calls.append(args)
            return {'code': 0, 'data': {'items': [[1]]}}
        self.service = DataSettings(self.path, metadata_path=self.metadata, transport=transport, resolver=public_dns, cooldown_seconds=0)

    def body(self, **values):
        return {'expectedRevision': self.service.describe()['revision'], 'endpoint': 'https://api.tushare.pro', 'token': '', 'allowInsecureHttp': False, **values}

    def error(self, code, fn):
        with self.assertRaises(SettingsError) as caught:
            fn()
        self.assertEqual(code, caught.exception.code)

    def test_describe_hides_secrets_and_never_resolves(self):
        with patch('socket.getaddrinfo', side_effect=AssertionError):
            dto = self.service.describe()
        self.assertTrue(dto['configured'])
        self.assertEqual(64, len(dto['revision']))
        self.assertNotIn('synthetic-secret', json.dumps(dto))
        self.assertEqual(3, len(dto['checks']))
        self.assertEqual([], self.calls)

    def test_save_preserves_mapping_and_blank_token_and_mode(self):
        old = yaml.safe_load(self.path.read_text())
        result = self.service.save(self.body())
        saved = yaml.safe_load(self.path.read_text())
        self.assertEqual(old['risk'], saved['risk'])
        self.assertEqual(old['data']['other'], saved['data']['other'])
        self.assertEqual('synthetic-secret', saved['data']['tushare_token'])
        self.assertEqual(0o600, self.path.stat().st_mode & 0o777)
        self.assertEqual(self.service.describe(), result)
        self.assertEqual([], self.calls)

    def test_first_configuration_requires_token(self):
        self.path.write_text('data: {}\n')
        self.error('TOKEN_REQUIRED', lambda: self.service.save(self.body()))
        self.assertEqual({}, yaml.safe_load(self.path.read_text())['data'])

    def test_unchanged_destination_save_skips_dns(self):
        def boom(*args, **kwargs):
            raise AssertionError('unchanged endpoint must not resolve DNS')
        self.service.resolver = boom
        result = self.service.save(self.body())
        self.assertEqual('https://api.tushare.pro', result['endpoint'])

    def test_windows_without_fchmod_uses_acl_instead(self):
        import deck.data_settings as module
        class WindowsOs:
            name = 'nt'
            def __getattr__(self, name):
                if name == 'fchmod':
                    raise AttributeError(name)
                return getattr(os, name)
        with patch.object(module, 'os', WindowsOs()), \
             patch.object(module.getpass, 'getuser', return_value='quant-user'), \
             patch.object(module.subprocess, 'run') as run:
            self.service.save(self.body(token='replacement'))
        command = run.call_args.args[0]
        self.assertEqual(['icacls', command[1], '/inheritance:r', '/grant:r', 'quant-user:(F)'], command)
        self.assertTrue(Path(command[1]).name.startswith('.params-'))
        self.assertEqual({'check': True, 'stdout': module.subprocess.DEVNULL, 'stderr': module.subprocess.DEVNULL}, run.call_args.kwargs)
        self.assertEqual('replacement', yaml.safe_load(self.path.read_text())['data']['tushare_token'])

    def test_describe_reports_current_data_mode(self):
        self.assertEqual('cache', self.service.describe()['dataMode']['kind'])
        with patch.dict(os.environ, {'LWQUANT_CACHE_DIR': 'data/demo'}):
            dto = self.service.describe()
        self.assertEqual('demo', dto['dataMode']['kind'])
        self.assertIn('不会切换', dto['dataMode']['note'])

    def test_dns_failure_does_not_consume_cooldown(self):
        service = DataSettings(self.path, metadata_path=self.metadata, transport=self.service.transport,
                               resolver=lambda *args, **kwargs: [], cooldown_seconds=30)
        self.error('INVALID_ENDPOINT', lambda: service.verify({'expectedRevision': service.describe()['revision']}))
        service.resolver = public_dns
        result = service.verify({'expectedRevision': service.describe()['revision']})
        self.assertEqual(['available'] * 3, [v['status'] for v in result['checks']])

    def test_revision_destination_and_explicit_http_confirmation(self):
        self.error('REVISION_CONFLICT', lambda: self.service.save(self.body(expectedRevision='old')))
        self.error('TOKEN_REQUIRED', lambda: self.service.save(self.body(endpoint='https://relay.example/pro')))
        self.error('INVALID_REQUEST', lambda: self.service.save(self.body(endpoint='http://relay.example/pro', token='new', allowInsecureHttp=1)))
        self.error('INSECURE_HTTP_CONFIRMATION_REQUIRED', lambda: self.service.save(self.body(endpoint='http://relay.example/pro', token='new')))
        result = self.service.save(self.body(endpoint='http://relay.example/pro', token='new', allowInsecureHttp=True))
        self.assertEqual('http://relay.example/pro', result['endpoint'])
        self.assertTrue(result['allowInsecureHttp'])
        self.error('INVALID_REQUEST', lambda: self.service.save(self.body(extra=True)))

    def test_legacy_secret_url_never_echoed(self):
        self.path.write_text('data:\n  tushare_api_url: https://user:password@relay.example?token=secret\n  tushare_token: <your-config>\n')
        dto = self.service.describe()
        self.assertFalse(dto['configured'])
        self.assertEqual('', dto['endpoint'])
        self.assertNotIn('password', json.dumps(dto))

    def test_symlink_and_oversized_config_rejected(self):
        link = self.path.parent / 'link.yaml'
        link.symlink_to(self.path)
        self.error('CONFIG_READ_FAILED', lambda: DataSettings(link).describe())
        self.path.write_bytes(b'x' * (1024 * 1024 + 1))
        self.error('CONFIG_READ_FAILED', self.service.describe)

    def test_endpoint_public_only_and_no_mixed_dns(self):
        for url in ['http://127.0.0.1', 'https://u:p@x', 'https://x?a=b', 'https://x/#f', 'https://x\n', 'https://x\\a', 'https://224.0.0.1']:
            self.error('INVALID_ENDPOINT', lambda: resolve_endpoint(url, public_dns))
        mixed = lambda *a, **k: public_dns() + [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        self.error('INVALID_ENDPOINT', lambda: resolve_endpoint('https://relay.example', mixed))

    def test_verify_three_small_queries_revision_and_safe_results(self):
        revision = self.service.describe()['revision']
        result = self.service.verify({'expectedRevision': revision})
        self.assertEqual(['available'] * 3, [v['status'] for v in result['checks']])
        self.assertEqual(['daily', 'adj_factor', 'fina_indicator'], [v[1]['api_name'] for v in self.calls])
        for endpoint, payload, ip, timeout, cap in self.calls:
            self.assertEqual('8.8.8.8', ip)
            self.assertEqual('synthetic-secret', payload['token'])
            self.assertIn('ts_code', payload['params'])
            self.assertLessEqual(payload['params']['limit'], 5)
        self.error('REVISION_CONFLICT', lambda: self.service.verify({'expectedRevision': 'old'}))
        self.assertNotIn('synthetic-secret', json.dumps(result))

    def test_per_api_errors_are_safe_and_independent(self):
        answers = iter([{'code': -2001, 'msg': 'token无效 synthetic-secret'}, {'code': -2002, 'msg': '权限不足 synthetic-secret'}, {'code': 0, 'data': {'items': []}}])
        self.service.transport = lambda *a: next(answers)
        result = self.service.verify({'expectedRevision': self.service.describe()['revision']})
        self.assertEqual(['credentials', 'permission', 'empty'], [v['status'] for v in result['checks']])
        self.assertNotIn('synthetic-secret', json.dumps(result))

    def test_verify_process_shared_cooldown(self):
        self.service.cooldown_seconds = 10
        self.service.verify({'expectedRevision': self.service.describe()['revision']})
        other = DataSettings(self.path, metadata_path=self.metadata, transport=self.service.transport, resolver=public_dns, cooldown_seconds=10)
        self.error('VERIFY_COOLDOWN', lambda: other.verify({'expectedRevision': other.describe()['revision']}))

    def test_transport_bounds_body_and_refuses_redirects(self):
        from unittest.mock import MagicMock
        for status, raw, code in [(302, b'', 'UPSTREAM_ERROR'), (200, b'x' * 17, 'UPSTREAM_ERROR'), (429, b'', 'RATE_LIMITED')]:
            connection = MagicMock()
            response = connection.getresponse.return_value
            response.status = status
            response.read.return_value = raw
            with patch('deck.data_settings._PinnedHTTPSConnection', return_value=connection) as factory:
                self.error(code, lambda: PinnedTransport()('https://relay.example/custom', {'token': 'fake'}, '8.8.8.8', 2, 16))
            factory.assert_called_once_with('relay.example', 443, '8.8.8.8', 2)
            self.assertEqual('/custom', connection.request.call_args.args[1])
            connection.close.assert_called_once()
            if status == 200:
                response.read.assert_called_once_with(17)

    def test_https_connect_pins_ip_and_keeps_hostname_sni(self):
        from deck.data_settings import _PinnedHTTPSConnection
        with patch('deck.data_settings.ssl.create_default_context') as context, patch('deck.data_settings.socket.create_connection') as connect:
            connection = _PinnedHTTPSConnection('relay.example', 443, '8.8.8.8', 2)
            connection.connect()
            connect.assert_called_once_with(('8.8.8.8', 443), 2)
            context.return_value.wrap_socket.assert_called_once_with(connect.return_value, server_hostname='relay.example', do_handshake_on_connect=False)
            context.return_value.wrap_socket.return_value.do_handshake.assert_called_once()

    def test_atomic_replace_failure_preserves_original(self):
        original = self.path.read_bytes()
        with patch('deck.data_settings.os.replace', side_effect=OSError('private detail')):
            self.error('CONFIG_WRITE_FAILED', lambda: self.service.save(self.body(token='replacement')))
        self.assertEqual(original, self.path.read_bytes())
        self.assertEqual(['data_sources.json', 'params.yaml'], sorted(v.name for v in self.path.parent.iterdir()))

    def test_busy_gate_does_not_call_transport(self):
        self.service._gate['lock'].acquire()
        try:
            self.error('VERIFY_BUSY', lambda: self.service.verify({'expectedRevision': self.service.describe()['revision']}))
        finally:
            self.service._gate['lock'].release()
        self.assertEqual([], self.calls)

    def test_verification_network_exception_is_safe(self):
        self.service.transport = lambda *a: (_ for _ in ()).throw(OSError('synthetic-secret'))
        result = self.service.verify({'expectedRevision': self.service.describe()['revision']})
        self.assertEqual(['network'] * 3, [v['status'] for v in result['checks']])
        self.assertNotIn('synthetic-secret', json.dumps(result))

    def test_slow_dns_is_bounded_and_does_not_lock_describe(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            entered.set()
            release.wait(1)
            return public_dns()
        service = DataSettings(self.path, metadata_path=self.metadata, resolver=slow, dns_timeout=0.03)
        errors = []
        body = self.body(endpoint='https://relay.example/pro', token='new')
        def save():
            try:
                service.save(body)
            except SettingsError as error:
                errors.append(error.code)
        worker = threading.Thread(target=save)
        worker.start()
        self.assertTrue(entered.wait(0.5))
        described = threading.Event()
        reader = threading.Thread(target=lambda: (self.service.describe(), described.set()))
        reader.start()
        try:
            self.assertTrue(described.wait(0.1), 'DNS must not hold global config lock')
            worker.join(0.2)
            self.assertFalse(worker.is_alive(), 'DNS deadline must bound save')
            self.assertEqual(['NETWORK'], errors)
        finally:
            release.set()
            worker.join(2)
            reader.join(2)

    def test_deadline_interrupts_tls_handshake_after_socket_registration(self):
        from unittest.mock import MagicMock
        interrupted = threading.Event()
        raw, secured = MagicMock(), MagicMock()
        secured.shutdown.side_effect = lambda *args: interrupted.set()
        def handshake():
            interrupted.wait(0.3)
            raise OSError('synthetic TLS detail')
        secured.do_handshake.side_effect = handshake
        started = time.monotonic()
        with patch('deck.data_settings.socket.create_connection', return_value=raw), patch('deck.data_settings.ssl.create_default_context') as context:
            context.return_value.wrap_socket.return_value = secured
            self.error('NETWORK', lambda: PinnedTransport()('https://relay.example', {}, '8.8.8.8', 0.03, 64))
        self.assertLess(time.monotonic() - started, 0.2)
        secured.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        secured.close.assert_called()

    def test_save_rechecks_revision_after_dns(self):
        def changed(*args, **kwargs):
            self.path.write_text('data: {tushare_token: concurrently-changed}')
            return public_dns()
        self.service.resolver = changed
        self.error('REVISION_CONFLICT', lambda: self.service.save(self.body(endpoint='https://relay.example/pro', token='new')))
        self.assertIn('concurrently-changed', self.path.read_text())

    def test_total_deadline_interrupts_slow_headers_and_body(self):
        # A synthetic socket pair never reaches a real host. Peer drips often enough
        # to avoid an inactivity timeout, in headers, fixed bodies and chunk framing.
        for prefix, drip in [(b'HTTP/1.1 200 OK\r\nX-Slow: ', b'x'),
                             (b'HTTP/1.1 200 OK\r\nContent-Length: 10000\r\n\r\n', b' '),
                             (b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n', b'1')]:
            client, peer = socket.socketpair()
            stop = threading.Event()
            def sender():
                try:
                    peer.sendall(prefix)
                    while not stop.wait(0.01):
                        peer.sendall(drip)
                except OSError:
                    pass
            worker = threading.Thread(target=sender, daemon=True)
            worker.start()
            started = time.monotonic()
            fallback = threading.Timer(0.3, lambda: client.shutdown(socket.SHUT_RDWR))
            fallback.start()
            try:
                with patch('deck.data_settings.socket.create_connection', return_value=client):
                    self.error('NETWORK', lambda: PinnedTransport()('http://relay.example', {}, '8.8.8.8', 0.06, 64))
                self.assertLess(time.monotonic() - started, 0.2)
            finally:
                fallback.cancel()
                stop.set()
                peer.close()
                client.close()
                worker.join(1)

    def test_fetcher_rebuilds_sdk_after_config_changes(self):
        from data import fetcher_tushare as fetcher
        self.addCleanup(setattr, fetcher, '_PRO', None)
        with patch.object(fetcher, '_load_cfg') as cfg:
            cfg.return_value = {'tushare_token': 'first', 'tushare_api_url': 'https://first.example'}
            first = fetcher._pro()
            self.assertIs(first, fetcher._pro())
            cfg.return_value = {'tushare_token': 'second', 'tushare_api_url': 'https://second.example'}
            second = fetcher._pro()
            self.assertIsNot(first, second)
            self.assertEqual('second', second._token)
            self.assertEqual('https://second.example', second._endpoint)
            cfg.return_value['tushare_allow_insecure_http'] = True
            self.assertIsNot(second, fetcher._pro())

    def test_fetcher_parses_config_only_when_file_changes(self):
        from data import fetcher_tushare as fetcher
        path = Path(self.temp.name) / 'fetcher-params.yaml'
        path.write_text('data:\n  tushare_token: first\n', encoding='utf-8')
        for attribute, value in (('_CONFIG_PATH', path), ('_CFG', None), ('_CFG_SIGNATURE', None)):
            patcher = patch.object(fetcher, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with patch('yaml.safe_load', wraps=yaml.safe_load) as loader:
            self.assertEqual('first', fetcher._load_cfg()['tushare_token'])
            self.assertEqual(1, loader.call_count)
            self.assertIs(fetcher._load_cfg(), fetcher._load_cfg())
            self.assertEqual(1, loader.call_count)
            path.write_text('data:\n  tushare_token: second\n', encoding='utf-8')
            self.assertEqual('second', fetcher._load_cfg()['tushare_token'])
            self.assertEqual(2, loader.call_count)

if __name__ == '__main__':
    unittest.main()
