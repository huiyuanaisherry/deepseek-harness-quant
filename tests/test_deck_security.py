import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from deck import deck_server
from deck.web_security import Security


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'output').mkdir()
        (self.root / 'ui_v2').mkdir()
        self.secret = self.root / 'private'
        self.secret.write_text('PRIVATE-FIXTURE')
        (self.root / 'output' / 'link').symlink_to(self.secret)
        self.patch = patch.object(deck_server, 'BASE', self.root)
        self.patch.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), deck_server.Handler)
        self.server.security = Security(self.root / 'auth' / 'token')
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_port
        self.cookie = ''
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.patch.stop()
        self.tmp.cleanup()
    def request(self, path, body=None, origin=True, extra=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        headers = {'Cookie': self.cookie, 'Content-Type':'application/json', 'X-Quant-Request':'1'}
        if origin:
            headers['Origin'] = f'http://127.0.0.1:{self.port}'
        headers.update(extra or {})
        conn.request('GET' if body is None else 'POST', path, None if body is None else json.dumps(body), headers)
        response = conn.getresponse()
        data = response.read()
        cookie = response.getheader('Set-Cookie')
        conn.close()
        return response.status, data, cookie
    def login(self):
        status, _, cookie = self.request('/api/auth/login', {'token':self.server.security.token})
        self.assertEqual(status, 200)
        self.cookie = cookie.split(';')[0]
    def test_real_handler_containment_after_login(self):
        self.login()
        for path in ['/dl//' + str(self.secret), '/v2//' + str(self.secret), '/dl/../private', '/dl/%2e%2e/private', '/dl/link', '/v2/%2f' + str(self.secret)]:
            with self.subTest(path=path):
                status, data, _ = self.request(path)
                self.assertIn(status, (400,403,404))
                self.assertNotIn(b'PRIVATE-FIXTURE', data)
    def test_all_private_routes_and_csrf(self):
        for path in ['/', '/api/pool', '/v2/pages/control.html', '/api/proxy/api/settings.describe']:
            self.assertIn(self.request(path)[0], (401,303))
        self.assertEqual(self.request('/api/decide', {})[0], 401)
        self.login()
        self.assertEqual(self.request('/api/auth/logout', {}, origin=False)[0], 403)
        self.assertEqual(self.request('/api/auth/logout', {}, extra={'Origin':f'http://127.0.0.1:{self.port}.evil'})[0], 403)
        self.assertEqual(self.request('/api/auth/logout', {}, extra={'X-Quant-Request':''})[0], 403)
        self.assertEqual(self.request('/api/auth/logout', {})[0], 200)
        self.assertEqual(self.request('/api/pool')[0], 401)
    def test_body_and_proxy_bounds(self):
        self.login()
        self.assertEqual(self.request('/api/auth/logout', {'x':'x'*70000})[0], 413)
        self.assertEqual(self.request('/api/proxy/api/settings.describe')[0], 404)

    def test_settings_errors_do_not_disclose_upstream(self):
        from deck.model_settings import ModelSettings, SettingsError
        def broken(method, payload):
            raise SettingsError()
        self.server.model_settings = ModelSettings(broken)
        self.login()
        status, data, _ = self.request('/api/model-settings')
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(data)['code'], 'UPSTREAM_ERROR')
    def test_status_and_login_cookie(self):
        self.assertFalse(json.loads(self.request('/api/auth/status')[1])['authenticated'])
        self.assertEqual(self.request('/login')[0], 200)
        self.login()
        self.assertTrue(json.loads(self.request('/api/auth/status')[1])['authenticated'])

    def test_actions_require_post_origin_header_and_dispatch_queries(self):
        import subprocess
        import types
        calls = []
        updater = types.SimpleNamespace(start=lambda: calls.append(('update', {})) or {'ok':True})
        runner = types.SimpleNamespace(run_backtest=lambda **kw: calls.append(('backtest', kw)) or {'result':'fixture'})
        exporter = lambda *args, **kw: calls.append(('export', {})) or types.SimpleNamespace(returncode=0, stdout='fixture')
        actions = ['/api/manual_update', '/api/export_data', '/api/live/backtest_run?strategy=custom&topn=7&stocks=12&start=2023-01-01&end=2023-02-01']
        self.login()
        with patch.dict('sys.modules', {'data.manual_update':updater,'backtest.bt_runner':runner}), patch.object(subprocess, 'run', exporter):
            for action in actions:
                with self.subTest(action=action):
                    for headers in ({'Origin':'http://127.0.0.1:9999','X-Quant-Request':''},
                                    {'Origin':'http://127.0.0.1:9999'}, {'X-Quant-Request':''}):
                        status, _, _ = self.request(action, extra=headers)
                        self.assertEqual(status, 405)
                        self.assertEqual(calls, [])
                    self.assertEqual(self.request(action, {}, origin=False)[0], 403)
                    self.assertEqual(self.request(action, {}, extra={'Origin':'http://127.0.0.1:9999'})[0], 403)
                    self.assertEqual(self.request(action, {}, extra={'X-Quant-Request':''})[0], 403)
                    self.assertEqual(calls, [])
            self.assertEqual(self.request(actions[0], {})[0], 200)
            self.assertEqual(self.request(actions[1], {})[0], 200)
            self.assertEqual(self.request(actions[2], {})[0], 200)
            self.assertEqual([kind for kind, _ in calls], ['update','export','backtest'])
            self.assertEqual(calls[-1][1], {'strategy':'custom','topn':7,'stocks':12,'start':'2023-01-01','end':'2023-02-01'})
