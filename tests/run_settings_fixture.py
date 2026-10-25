"""Manual loopback-only UI fixture. No external network or real secrets.
Run: python3 tests/run_settings_fixture.py [--port 13187] [--partial-key-failure]
Login at /login with the synthetic token quant-fixture-token.
"""
import argparse
import copy
import sys
import tempfile
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deck.deck_server import Handler as QuantHandler
from deck.model_settings import ModelSettings, SettingsError
from deck.web_security import Security


class Handler(QuantHandler):
    """Expose only the settings workflow, never live research or proxy actions."""

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            if self._gate():
                self.send_response(303)
                self.send_header('Location', '/settings')
                self.send_header('Content-Length', '0')
                self.end_headers()
            return
        if path in ('/api/build_mode', '/api/live/portal_dash'):
            if self._gate():
                self._send_json({'mode': 'fixture', 'data_date': '合成测试', 'timing': {}})
            return
        allowed = {'/login', '/settings', '/api/auth/status',
                   '/api/model-settings', '/api/navigation'}
        if path in allowed or path.startswith(('/v2/assets/', '/v2/core/', '/v2/components/')):
            return super().do_GET()
        self._send_json({'ok': False, 'error': 'Fixture route unavailable'}, 404)

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        allowed = {'/api/auth/login', '/api/auth/logout', '/api/model-settings/provider',
                   '/api/model-settings/key/remove', '/api/model-settings/default'}
        if path in allowed:
            return super().do_POST()
        self._send_json({'ok': False, 'error': 'Fixture route unavailable'}, 404)


class FixtureTransport:
    def __init__(self, partial=False):
        self.partial = partial
        self.values = {'llm-deepseek': {}, 'llm-pi-ai': {'providers': {'fixture-compatible': {
            'displayName': '兼容服务商（测试）', 'api': 'openai-completions',
            'baseURL': 'https://api.example.com/v1', 'models': [{'id': 'fixture-model'}]}}}}
        self.revisions = {'llm-deepseek': 4, 'llm-pi-ai': 9}
        self.keys = {}
        self.default = {'provider': 'fixture-compatible', 'model': 'fixture-model'}
        self.default_revision = 2

    def __call__(self, method, payload):
        if method == 'llm.providers':
            return {'providers': [
                {'provider': 'deepseek', 'displayName': 'DeepSeek 原生', 'settingsNs': 'llm-deepseek', 'settingsPath': []},
                *[{'provider': key, 'displayName': value.get('displayName', key), 'settingsNs': 'llm-pi-ai', 'settingsPath': ['providers', key]} for key, value in self.values['llm-pi-ai']['providers'].items()]]}
        if method == 'llm.models':
            return {'groups': [{'id': 'deepseek', 'models': [{'id': 'deepseek-chat'}] if 'DEEPSEEK_API_KEY' in self.keys else []}]}
        if method == 'settings.describe':
            return {'namespaces': [{'ns': ns, 'revision': self.revisions[ns], 'value': copy.deepcopy(value)} for ns, value in self.values.items()]}
        if method == 'settings.mutate':
            ns = payload['ns']
            if payload['expectedRevision'] != self.revisions[ns]:
                raise SettingsError('REVISION_CONFLICT', 409)
            for op in payload['ops']:
                value = self.values[ns]
                for part in op['path'][:-1]:
                    value = value.setdefault(part, {})
                value[op['path'][-1]] = copy.deepcopy(op['value'])
            self.revisions[ns] += 1
            return {'revision': self.revisions[ns]}
        if method == 'credentials.describe':
            return {'credentials': {ref: {'configured': ref in self.keys, 'writable': True, 'source': 'store'} for ref in payload['refs']}}
        if method == 'credentials.set':
            if self.partial:
                raise SettingsError()
            self.keys[payload['ref']] = True  # Never retain even synthetic credential values.
            return {}
        if method == 'credentials.unset':
            self.keys.pop(payload['ref'], None)
            return {}
        if method == 'quant.defaults.describe':
            return {'ok': True, 'revision': self.default_revision, 'defaultModel': dict(self.default)}
        if method == 'quant.defaults.mutate':
            if payload['expectedRevision'] != self.default_revision:
                raise SettingsError('REVISION_CONFLICT', 409)
            self.default = {key: payload[key] for key in ('provider', 'model')}
            self.default_revision += 1
            return {'revision': self.default_revision}
        raise AssertionError('Unexpected RPC: ' + method)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=13187)
    parser.add_argument('--partial-key-failure', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='quant-ui-fixture-') as directory:
        token_path = Path(directory) / 'token'
        token_path.write_text('quant-fixture-token')
        token_path.chmod(0o600)
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
        server.security = Security(token_path)
        server.model_settings = ModelSettings(FixtureTransport(args.partial_key_failure))
        # Fixture endpoints are deliberately allowed without DNS or remote requests.
        import deck.model_settings as settings_module
        settings_module.validate_endpoint = lambda url: url if url == 'https://api.example.com/v1' else (_ for _ in ()).throw(SettingsError('INVALID_ENDPOINT', 400))
        print(f'Fixture: http://127.0.0.1:{args.port}/settings (synthetic token: quant-fixture-token)', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
