// rc.6 hides agent-default-model from its generic settings RPC allowlist.
// This narrow loopback route keeps persistence and revisions in native settings.
const { isIP } = require('node:net');
const NAMESPACE = 'agent-default-model';
const MAX_BODY = 4096;

function loopback(address) {
  if (typeof address !== 'string') return false;
  if (address === '::1') return true;
  const ipv4 = address.startsWith('::ffff:') ? address.slice(7) : address;
  return isIP(ipv4) === 4 && ipv4.startsWith('127.');
}

function identifier(value) {
  return typeof value === 'string' && value.length > 0 && value.length <= 256 && !/[\x00-\x1f\x7f]/.test(value);
}

function send(res, status, value) {
  res.writeHead(status, { 'Content-Type':'application/json; charset=utf-8', 'Cache-Control':'no-store' });
  res.end(JSON.stringify(value));
}

function fail(res, status, code) {
  send(res, status, { ok:false, code, error:code.replaceAll('_', ' ').toLowerCase() });
}

async function readBody(req) {
  const declared = req.headers['content-length'];
  if (declared !== undefined && (!/^\d+$/.test(declared) || Number(declared) > MAX_BODY)) return { error:413 };
  const chunks = [];
  let size = 0;
  for await (const chunk of req.iterator({ destroyOnReturn:false })) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_BODY) { req.resume(); return { error:413 }; }
    chunks.push(buffer);
  }
  try {
    const value = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (value === null || Array.isArray(value) || typeof value !== 'object') return { error:400 };
    return { value };
  } catch { return { error:400 }; }
}

module.exports = {
  inject:['webServer', 'settings', 'agentDefaultModel'],
  apply(ctx) {
    const settings = ctx.get('settings');
    const defaults = ctx.get('agentDefaultModel');
    const view = () => {
      const descriptor = settings.describe({ redactSecrets:true }).find(row => row.ns === NAMESPACE);
      const current = defaults.currentSelection();
      if (!descriptor || !Number.isInteger(descriptor.revision) || !identifier(current.provider) || !identifier(current.model)) throw new Error('Unavailable');
      return { ok:true, defaultModel:{ provider:current.provider, model:current.model }, revision:descriptor.revision };
    };
    ctx.effect(() => ctx.get('webServer').register({
      kind:'exact', path:'/quant/model-default',
      async handler(req, res) {
        const host = req.headers.host;
        let hostLoopback = false;
        try { hostLoopback = typeof host === 'string' && loopback(new URL('http://' + host).hostname.replace(/^\[|\]$/g, '')); } catch {}
        if (!loopback(req.socket?.remoteAddress) || !hostLoopback || req.headers.origin !== 'http://' + host || req.headers['x-quant-request'] !== '1') return fail(res, 403, 'FORBIDDEN');
        if (req.method !== 'GET' && req.method !== 'POST') return fail(res, 405, 'METHOD_NOT_ALLOWED');
        try {
          if (req.method === 'GET') return send(res, 200, view());
          if ((req.headers['content-type'] || '').split(';')[0].trim().toLowerCase() !== 'application/json') return fail(res, 415, 'INVALID_JSON');
          const body = await readBody(req);
          if (body.error) return fail(res, body.error, body.error === 413 ? 'BODY_TOO_LARGE' : 'INVALID_JSON');
          const value = body.value;
          if (Object.keys(value).some(key => !['provider','model','expectedRevision'].includes(key)) || !identifier(value.provider) || !identifier(value.model) || !Number.isInteger(value.expectedRevision) || value.expectedRevision < 0) return fail(res, 400, 'INVALID_REQUEST');
          await settings.mutate(NAMESPACE, [
            { op:'set', path:['provider'], value:value.provider },
            { op:'set', path:['model'], value:value.model },
            { op:'unset', path:['reasoningEffort'] }
          ], value.expectedRevision);
          return send(res, 200, view());
        } catch (error) {
          return fail(res, error?.name === 'SettingsConflictError' ? 409 : 502,
                      error?.name === 'SettingsConflictError' ? 'REVISION_CONFLICT' : 'UPSTREAM_ERROR');
        }
      }
    }));
  }
};
