import copy
import unittest
from deck.model_settings import ModelSettings, SettingsError, validate_endpoint


class Fake:
    def __init__(self):
        self.profile = {'apiKeyEnv': 'MOCK_API_KEY', 'models': [{'id': 'mock-model'}], 'secret': 'PRIVATE', 'unowned': 42}
        self.calls = []
        self.fail_key = False
    def __call__(self, method, payload):
        self.calls.append((method, copy.deepcopy(payload)))
        if method == 'quant.defaults.describe':
            return {'ok':True,'defaultModel':{'provider':'mock','model':'mock-model'},'revision':2}
        if method == 'quant.defaults.mutate':
            return {'ok':True,'defaultModel':{'provider':payload['provider'],'model':payload['model']},'revision':3}
        if method == 'llm.providers':
            return {'providers': [{'provider':'mock','displayName':'Mock','settingsNs':'llm-pi-ai','settingsPath':['providers','mock']}]}
        if method == 'settings.describe':
            return {'writable':True,'namespaces':[
                {'ns':'llm-pi-ai','revision':3,'value':{'providers':{'mock': self.profile}}},
                {'ns':'agent-default-model','revision':2,'value':{'provider':'mock','model':'mock-model','secret':'PRIVATE'}}]}
        if method == 'credentials.describe':
            return {'credentials':{'MOCK_API_KEY':{'configured':True,'writable':True,'source':'store','value':'PRIVATE'}}}
        if method == 'credentials.set' and self.fail_key:
            raise SettingsError('UPSTREAM_ERROR')
        if method == 'settings.mutate':
            return {'revision':4}
        return {}


class SettingsTests(unittest.TestCase):
    def test_projection_preservation_conflict_partial(self):
        fake = Fake()
        service = ModelSettings(fake)
        view = service.describe()
        self.assertNotIn('PRIVATE', str(view))
        self.assertEqual(view['providers'][0]['id'], 'mock')
        with self.assertRaises(SettingsError):
            service.save({'provider':'mock','expectedRevision':0})
        fake.fail_key = True
        result = service.save({'provider':'mock','displayName':'Changed','expectedRevision':3,'apiKey':'FAKE-KEY'})
        self.assertTrue(result['partial'])
        ops = [p for m,p in fake.calls if m == 'settings.mutate'][-1]['ops']
        self.assertFalse(any('unowned' in op['path'] for op in ops))
        self.assertNotIn('FAKE-KEY', str(result))

    def test_endpoint_rejects_private(self):
        for url in ['http://example.com', 'https://127.0.0.1', 'https://user:pass@example.com', 'https://example.com/?key=x', 'https://[::1]']:
            with self.subTest(url=url), self.assertRaises(SettingsError):
                validate_endpoint(url)


class TransportTests(unittest.TestCase):
    def test_rejected_redirect_closes_the_upstream_response(self):
        import io
        from deck.model_settings import NoRedirect
        response = io.BytesIO(b'untrusted upstream response')
        with self.assertRaises(SettingsError):
            NoRedirect().redirect_request(None, response, 302, 'Found', {}, 'https://example.com')
        self.assertTrue(response.closed)

    def test_real_http_envelope_and_safe_errors(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from deck.model_settings import DSHClient
        seen = []
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append((self.path, body))
                if body['method'] == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', '/FAKE_SECRET')
                    self.end_headers()
                    return
                result = {'ok':True,'value':{'providers':[]}} if body['method']=='llm.providers' else {'ok':False,'error':{'message':'FAKE_SECRET','code':'settings-conflict'}}
                data = json.dumps({'type':'server-response','rpcId':body['rpcId'],'result':result}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = DSHClient(f'http://127.0.0.1:{server.server_port}')
            self.assertEqual(client('llm.providers', {}), {'providers':[]})
            self.assertEqual(seen[0][0], '/api/llm.providers')
            self.assertEqual(seen[0][1]['type'], 'client-request')
            self.assertEqual(seen[0][1]['payload'], {})
            for method in ('error','redirect'):
                with self.assertRaises(SettingsError) as error:
                    client(method, {})
                self.assertNotIn('FAKE_SECRET', str(error.exception))
            self.assertEqual(len(seen), 3)
        finally:
            server.shutdown()
            server.server_close()

    def test_native_catalog_models_without_profile(self):
        fake = Fake()
        fake.profile.pop('models')
        original = fake.__call__
        def rpc(method, payload):
            if method == 'llm.models':
                return {'groups':[{'id':'mock','name':'Mock','models':[{'id':'native','name':'Native','secret':'PRIVATE'}]}]}
            return original(method, payload)
        service = ModelSettings(rpc)
        self.assertEqual(service.describe()['providers'][0]['models'], [{'id':'native','name':'Native'}])
        self.assertTrue(service.set_default({'provider':'mock','model':'native','expectedRevision':2})['ok'])


class MutationTests(unittest.TestCase):
    def test_remove_resolves_ref_and_default_preserves_unowned(self):
        fake = Fake()
        service = ModelSettings(fake)
        service.remove_key({'provider':'mock','ref':'ATTACKER_REF'})
        self.assertEqual(fake.calls[-1], ('credentials.unset', {'ref':'MOCK_API_KEY'}))
        service.set_default({'provider':'mock','model':'mock-model','expectedRevision':2})
        self.assertEqual(fake.calls[-1], ('quant.defaults.mutate', {'provider':'mock','model':'mock-model','expectedRevision':2}))
        with self.assertRaises(SettingsError):
            service.set_default({'provider':'mock','model':'wrong','expectedRevision':2})
    def test_blank_key_preserved_and_unknown_fields_ignored(self):
        fake = Fake()
        ModelSettings(fake).save({'provider':'mock','apiKey':'','expectedRevision':3, 'apiKeyEnv':'ATTACKER'})
        self.assertFalse(any(m.startswith('credentials.') and m != 'credentials.describe' for m,p in fake.calls))
        self.assertFalse(any(m == 'settings.mutate' for m,p in fake.calls))
    def test_mixed_dns_rejected(self):
        from unittest.mock import patch
        with patch('deck.model_settings.socket.getaddrinfo', return_value=[(2,1,6,'',('8.8.8.8',443)), (2,1,6,'',('10.0.0.1',443))]):
            with self.assertRaises(SettingsError):
                validate_endpoint('https://public.example/v1')
    def test_proxy_allowlist_mapping_and_projection(self):
        from deck.model_settings import proxy_quant
        class Upstream:
            def request(self, path, data):
                self.path = path
                return {'ok':True,'sessions':[{'id':'one','title':'A','apiKey':'PRIVATE'}], 'debug':'PRIVATE'}
        upstream = Upstream()
        result = proxy_quant('/api/proxy/quantapi/sessions', 'GET', client=upstream)
        self.assertEqual(upstream.path, '/quant/sessions')
        self.assertNotIn('PRIVATE', str(result))
        for path in ('/api/proxy/api/credentials.describe','/api/proxy/quantapi/delete', '/api/proxy/quant/agents', '/api/proxy/quant/sessions/../settings'):
            with self.assertRaises(SettingsError):
                proxy_quant(path,'GET',client=upstream)

    def test_malformed_rpc_nested_envelopes_are_safe_upstream_errors(self):
        from deck.model_settings import DSHClient
        from unittest.mock import patch
        client = DSHClient()
        for result in (None, [], {'ok':False,'error':None}, {'ok':False,'error':['FAKE_SECRET']}):
            with self.subTest(result=result), patch.object(client, 'request', side_effect=lambda path, raw: {'type':'server-response','rpcId':__import__('json').loads(raw)['rpcId'],'result':result}):
                with self.assertRaises(SettingsError) as error:
                    client('llm.providers', {})
                self.assertEqual(error.exception.code, 'UPSTREAM_ERROR')
                self.assertEqual(error.exception.status, 502)
                self.assertNotIn('FAKE_SECRET', str(error.exception))

    def test_compatibility_defaults_transport_mapping_and_validation(self):
        from deck.model_settings import DSHClient
        from unittest.mock import patch
        client = DSHClient()
        value = {'ok':True,'defaultModel':{'provider':'mock','model':'one'},'revision':3}
        with patch.object(client, 'request', return_value=value) as request:
            self.assertEqual(client('quant.defaults.describe', {}), value)
            request.assert_called_once_with('/quant/model-default', None)
        with patch.object(client, 'request', return_value=value) as request:
            client('quant.defaults.mutate', {'provider':'mock','model':'one','expectedRevision':2})
            self.assertEqual(request.call_args.args[0], '/quant/model-default')
            self.assertEqual(__import__('json').loads(request.call_args.args[1]), {'provider':'mock','model':'one','expectedRevision':2})
        for malformed in ({'ok':True}, {'ok':True,'defaultModel':{},'revision':3}, {'ok':False,'error':'FAKE_SECRET'}):
            with patch.object(client, 'request', return_value=malformed), self.assertRaises(SettingsError):
                client('quant.defaults.describe', {})


class SessionCreationTests(unittest.TestCase):
    def test_native_creation_is_fixed_empty_payload_and_projects_id_only(self):
        from deck.model_settings import create_chat_session
        calls=[]
        def rpc(method,payload):
            calls.append((method,payload))
            return {'sessionId':'session-test','apiKey':'PRIVATE'}
        self.assertEqual(create_chat_session({}, rpc), {'ok':True,'sessionId':'session-test'})
        self.assertEqual(calls,[('session.create',{})])
        for payload in ({'cwd':'/private'},{'agentPreset':'override'},None,[]):
            with self.assertRaises(SettingsError):
                create_chat_session(payload,rpc)
        self.assertEqual(len(calls),1)
        for response in ({}, {'sessionId':''}, {'sessionId':['PRIVATE']}):
            with self.assertRaises(SettingsError):
                create_chat_session({},lambda *args:response)
