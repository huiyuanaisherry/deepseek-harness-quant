"""UI catalog fixture and navigation contract; no external requests."""
import importlib.util
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from deck.model_settings import ModelSettings
from deck.web_security import Security

spec = importlib.util.spec_from_file_location('settings_fixture', Path(__file__).with_name('run_settings_fixture.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class SettingsUITests(unittest.TestCase):
    def test_browser_fixture_cannot_reach_real_business_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            server = ThreadingHTTPServer(('127.0.0.1', 0), fixture.Handler)
            server.security = Security(Path(directory) / 'token')
            session = server.security.login(server.security.token, 'fixture')
            server.model_settings = ModelSettings(fixture.FixtureTransport())
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.object(fixture.Handler, '_private_GET', side_effect=AssertionError('real read')), \
                     patch.object(fixture.Handler, '_private_POST', side_effect=AssertionError('real write')), \
                     patch('deck.deck_server.proxy_quant', side_effect=AssertionError('real upstream')):
                    for method, path in [('GET', '/api/portfolio'), ('GET', '/api/proxy/quantapi/sessions'),
                                         ('POST', '/api/import/install'), ('POST', '/api/manual_update'),
                                         ('POST', '/api/decide'), ('POST', '/api/proxy/quantapi/chat2')]:
                        with self.subTest(method=method, path=path):
                            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
                            headers = {'Cookie': 'quant_session=' + session,
                                       'Origin': f'http://127.0.0.1:{server.server_port}',
                                       'X-Quant-Request': '1', 'Content-Type': 'application/json'}
                            conn.request(method, path, '{}' if method == 'POST' else None, headers)
                            response = conn.getresponse()
                            self.assertEqual(response.status, 404)
                            response.read()
                            conn.close()
            finally:
                server.shutdown()
                server.server_close()

    def test_native_key_default_and_removal(self):
        transport = fixture.FixtureTransport()
        service = ModelSettings(transport)
        self.assertEqual(service.describe()['providers'][0]['models'], [])
        service.save({'provider': 'deepseek', 'apiKey': 'synthetic-key', 'expectedRevision': 4})
        catalog = service.describe()
        self.assertEqual(catalog['providers'][0]['models'][0]['id'], 'deepseek-chat')
        self.assertNotIn('synthetic-key', json.dumps(catalog))
        service.set_default({'provider': 'deepseek', 'model': 'deepseek-chat', 'expectedRevision': 2})
        self.assertEqual(service.describe()['defaultModel']['provider'], 'deepseek')
        service.remove_key({'provider': 'deepseek'})
        self.assertFalse(service.describe()['providers'][0]['credential']['configured'])

    def test_partial_save_advances_revision_without_key(self):
        service = ModelSettings(fixture.FixtureTransport(partial=True))
        result = service.save({'provider': 'deepseek', 'apiKey': 'synthetic-key', 'expectedRevision': 4})
        self.assertTrue(result['partial'])
        self.assertEqual(service.describe()['providers'][0]['revision'], result['revision'])
        self.assertFalse(service.describe()['providers'][0]['credential']['configured'])

    def test_navigation_template_matches_and_includes_settings(self):
        root = Path(__file__).resolve().parents[1] / 'config'
        value = json.loads((root / 'navigation.json').read_text())
        self.assertEqual(value, json.loads((root / 'navigation.json.example').read_text()))
        self.assertTrue(any(row['url'] == '/settings' for row in value['more']))
