"""Restricted DSH settings facade. No generic management RPC is exposed."""
import ipaddress
import json
import os
import re
import socket
import uuid
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

PROTOCOLS = ['openai-completions', 'openai-responses', 'anthropic-messages']
MAX_RESPONSE = 2 * 1024 * 1024


class SettingsError(Exception):
    def __init__(self, code='UPSTREAM_ERROR', status=502):
        self.code, self.status = code, status
        super().__init__(code.replace('_', ' ').capitalize())


def text(value, limit=256):
    return isinstance(value, str) and 0 < len(value) <= limit and not any(ord(c) < 32 for c in value)


def validate_endpoint(url):
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username is not None or p.password is not None or p.query or p.fragment or '\\' in url:
            raise ValueError()
        answers = socket.getaddrinfo(p.hostname, p.port or 443, type=socket.SOCK_STREAM)
        if not answers or any(not ipaddress.ip_address(answer[4][0]).is_global for answer in answers):
            raise ValueError()
        return url
    except (ValueError, TypeError, OSError):
        raise SettingsError('INVALID_ENDPOINT', 400) from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SettingsError()


class DSHClient:
    def __init__(self, base=None):
        self.base = base or os.environ.get('DSH_API_URL', 'http://127.0.0.1:3080')
        p = urlsplit(self.base)
        try:
            if p.scheme != 'http' or not ipaddress.ip_address(p.hostname).is_loopback or p.username or p.password or p.path not in ('', '/') or p.query or p.fragment:
                raise ValueError()
            p.port
        except (ValueError, TypeError):
            raise SettingsError('INVALID_UPSTREAM', 500) from None
        self.base = self.base.rstrip('/')
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, data=None):
        try:
            request = Request(self.base + path, data=data, headers={'Content-Type':'application/json'})
            with self.opener.open(request, timeout=10) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise SettingsError()
                return json.loads(raw)
        except Exception:
            raise SettingsError() from None

    def __call__(self, method, payload):
        rpc_id = str(uuid.uuid4())
        result = self.request('/api/' + method, json.dumps({'type':'client-request','rpcId':rpc_id,'method':method,'payload':payload}).encode())
        if not isinstance(result, dict) or result.get('rpcId') != rpc_id or result.get('type') != 'server-response':
            raise SettingsError()
        envelope = result.get('result', {})
        if not isinstance(envelope, dict):
            raise SettingsError()
        if envelope.get('ok') is not True:
            error = envelope.get('error')
            code = error.get('code') if isinstance(error, dict) else None
            raise SettingsError('REVISION_CONFLICT' if code == 'settings-conflict' else 'UPSTREAM_ERROR', 409 if code == 'settings-conflict' else 502)
        value = envelope.get('value')
        if not isinstance(value, dict):
            raise SettingsError()
        return value


def at(value, path):
    for part in path:
        value = value.get(part) if isinstance(value, dict) else None
    return value if isinstance(value, dict) else {}


def models(value):
    if not isinstance(value, list):
        return []
    return [{'id':m['id'], **({'name':m['name']} if text(m.get('name')) else {})}
            for m in value[:256] if isinstance(m, dict) and text(m.get('id'))]


class ModelSettings:
    def __init__(self, transport=None):
        self.rpc = transport or DSHClient()

    def _load(self):
        catalog = self.rpc('llm.providers', {}).get('providers', [])
        groups = self.rpc('llm.models', {}).get('groups', [])
        catalog_models = {g['id']: models(g.get('models')) for g in groups if isinstance(g, dict) and text(g.get('id'))}
        description = self.rpc('settings.describe', {})
        namespaces = {v['ns']:v for v in description.get('namespaces', []) if isinstance(v, dict) and isinstance(v.get('ns'), str)}
        rows = []
        for entry in catalog:
            if not isinstance(entry, dict):
                continue
            identifier = entry.get('provider', entry.get('id'))
            path = entry.get('settingsPath')
            ns = entry.get('settingsNs')
            if not text(identifier) or not text(ns) or not isinstance(path, list) or len(path)>16 or any(not text(p) for p in path):
                continue
            profile = at(namespaces.get(ns, {}).get('value', {}), path)
            entry = {**entry, 'models':catalog_models.get(identifier, entry.get('models', []))}
            rows.append((entry, identifier, profile))
        return rows, namespaces

    def _ref(self, identifier, profile):
        ref = profile.get('apiKeyEnv')
        if ref is None:
            ref = re.sub('[^A-Z0-9]+', '_', identifier.upper()) + '_API_KEY'
        if not isinstance(ref, str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}', ref):
            raise SettingsError('INVALID_CREDENTIAL_REFERENCE', 400)
        return ref

    def describe(self):
        rows, namespaces = self._load()
        refs = list(dict.fromkeys(self._ref(i,p) for _,i,p in rows))
        credentials = {}
        for index in range(0, len(refs), 64):
            credentials.update(self.rpc('credentials.describe', {'refs':refs[index:index+64]}).get('credentials', {}))
        providers = []
        for entry, identifier, profile in rows:
            safe = {k:profile[k] for k in ('api','displayName') if text(profile.get(k))}
            endpoint = profile.get('baseURL')
            if text(endpoint, 2048):
                try:
                    p = urlsplit(endpoint)
                    if p.scheme == 'https' and p.hostname and not p.username and not p.password and not p.query and not p.fragment:
                        safe['baseURL'] = endpoint
                except ValueError:
                    pass
            safe['models'] = models(profile.get('models', entry.get('models', [])))
            credential = credentials.get(self._ref(identifier, profile), {})
            source = credential.get('source')
            providers.append({'id':identifier, 'name':entry.get('displayName', identifier) if text(entry.get('displayName')) else identifier,
                              'settingsNs':entry['settingsNs'], 'settingsPath':entry['settingsPath'], 'models':safe['models'],
                              'profile':safe, 'revision':namespaces.get(entry['settingsNs'], {}).get('revision'),
                              'credential':{'configured':credential.get('configured') is True, 'writable':credential.get('writable') is True,
                                            **({'source':source} if source in ('store','env','environment','credentials','file','memory','settings') else {})}})
        defaults = namespaces.get('agent-default-model', {})
        value = defaults.get('value', {})
        return {'ok':True, 'providers':providers, 'revision':namespaces.get('llm-pi-ai', {}).get('revision'),
                'defaultRevision':defaults.get('revision'), 'defaultModel':{k:value[k] for k in ('provider','model') if text(value.get(k))}, 'protocols':PROTOCOLS}

    def _find(self, identifier, rows):
        return next(((e,p) for e,i,p in rows if i == identifier), (None, {}))

    def _revision(self, body, namespace):
        expected = body.get('expectedRevision')
        if type(expected) is not int or expected != namespace.get('revision'):
            raise SettingsError('REVISION_CONFLICT', 409)
        return expected

    def save(self, body):
        identifier = body.get('provider')
        if not isinstance(identifier, str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}', identifier):
            raise SettingsError('INVALID_PROVIDER', 400)
        rows, namespaces = self._load()
        entry, profile = self._find(identifier, rows)
        ns = entry['settingsNs'] if entry else 'llm-pi-ai'
        path = entry['settingsPath'] if entry else ['providers', identifier]
        expected = self._revision(body, namespaces.get(ns, {}))
        ops = []
        if not entry:
            # A custom route needs a protocol, endpoint and explicit models.
            if not all(k in body for k in ('api','baseURL','models')):
                raise SettingsError('INVALID_PROFILE', 400)
        for field in ('displayName', 'api', 'baseURL', 'models'):
            if field not in body:
                continue
            value = body[field]
            if field == 'baseURL':
                if not text(value, 2048):
                    raise SettingsError('INVALID_ENDPOINT', 400)
                validate_endpoint(value)
            elif field == 'api':
                if value not in PROTOCOLS:
                    raise SettingsError('INVALID_PROTOCOL', 400)
            elif field == 'models':
                if not isinstance(value, list) or not value or len(value)>256 or len(models(value)) != len(value):
                    raise SettingsError('INVALID_MODELS', 400)
                # Preserve metadata of existing models; form owns IDs and names only.
                previous = {m.get('id'):m for m in profile.get('models', []) if isinstance(m, dict)}
                value = [{**previous.get(m['id'], {}), **m} for m in models(value)]
            elif not text(value):
                raise SettingsError('INVALID_PROFILE', 400)
            ops.append({'op':'set','path':path+[field], 'value':value})
        key = body.get('apiKey')
        if key is not None and (not isinstance(key, str) or len(key)>8192 or any(ord(c)<32 for c in key)):
            raise SettingsError('INVALID_KEY', 400)
        if key:
            ref = self._ref(identifier, profile)
            if profile.get('apiKeyEnv') != ref:
                ops.append({'op':'set','path':path+['apiKeyEnv'],'value':ref})
        revision = expected
        if ops:
            revision = self.rpc('settings.mutate', {'ns':ns,'ops':ops,'expectedRevision':expected}).get('revision')
        if key:
            try:
                self.rpc('credentials.set', {'ref':ref,'value':key})
            except SettingsError:
                return {'ok':False,'partial':True,'profileCommitted':True,'revision':revision,'code':'CREDENTIAL_WRITE_FAILED','error':'Profile saved; credential write failed'}
        return {'ok':True,'revision':revision}

    def remove_key(self, body):
        rows, _ = self._load()
        entry, profile = self._find(body.get('provider'), rows)
        if not entry:
            raise SettingsError('UNKNOWN_PROVIDER', 400)
        self.rpc('credentials.unset', {'ref':self._ref(body['provider'], profile)})
        return {'ok':True}

    def set_default(self, body):
        rows, namespaces = self._load()
        entry, profile = self._find(body.get('provider'), rows)
        model = body.get('model')
        if not entry or not text(model) or model not in [m['id'] for m in models(profile.get('models', entry.get('models', [])))]:
            raise SettingsError('INVALID_MODEL', 400)
        expected = self._revision(body, namespaces.get('agent-default-model', {}))
        result = self.rpc('settings.mutate', {'ns':'agent-default-model', 'expectedRevision':expected,
                                            'ops':[{'op':'set','path':[k],'value':body[k]} for k in ('provider','model')]})
        return {'ok':True,'defaultRevision':result.get('revision')}


def proxy_quant(target, method, body=None, client=None):
    """Only the installed quant bridge's known routes; never host API RPCs."""
    from urllib.parse import parse_qs, urlencode
    parsed = urlsplit(target)
    route = parsed.path.removeprefix('/api/proxy/') if hasattr(str, 'removeprefix') else parsed.path[len('/api/proxy/'):]
    aliases = {'quantapi/sessions':'quant/sessions', 'quantapi/recent':'quant/recent',
               'quantapi/chat2':'quant/chat2', 'niuapi/sessions':'quant/niu/sessions',
               'niuapi/recent':'quant/niu/recent', 'niuapi/chat':'quant/niu/chat'}
    route = aliases.get(route, route)
    allowed = {'GET':{'quant/sessions','quant/recent','quant/niu/sessions','quant/niu/recent'},
               'POST':{'quant/chat2','quant/niu/chat'}}
    if route not in allowed.get(method, set()):
        raise SettingsError('UNSUPPORTED_ROUTE', 404)
    query = parse_qs(parsed.query, max_num_fields=8)
    if any(k not in ('persona','sessionId','limit') or len(v) != 1 or not text(v[0], 256) for k,v in query.items()):
        raise SettingsError('INVALID_REQUEST', 400)
    path = '/' + route + ('?' + urlencode({k:v[0] for k,v in query.items()}) if query else '')
    data = None
    if method == 'POST':
        keys = ('persona','text','snapshot') if route.endswith('/niu/chat') else ('text','sessionId')
        if any(k not in keys for k in body) or not text(body.get('text'), 60000):
            raise SettingsError('INVALID_REQUEST', 400)
        data = json.dumps(body).encode()
    response = (client or DSHClient()).request(path, data)
    if not isinstance(response, dict) or response.get('ok') is False:
        raise SettingsError()
    # Upstream debug/error/config payloads are deliberately not part of this facade.
    def project(row, keys):
        return {k:v for k,v in row.items() if k in keys and isinstance(v, (str,int,float,bool,type(None)))} if isinstance(row, dict) else {}
    result = {'ok':True}
    for field, keys in [('sessions', ('id','title','preview','role','ts','current')), ('personas', ('key','id','name','persona','title','preview','childId')), ('messages', ('id','role','text','content','ts','timestamp'))]:
        if isinstance(response.get(field), list):
            result[field] = [project(row, keys) for row in response[field][:500]]
    result.update(project(response, ('sessionId','persona','childId','text','reply','accepted','busy')))
    return result
