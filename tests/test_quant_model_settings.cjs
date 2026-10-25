const test = require('node:test');
const assert = require('node:assert/strict');
const { Readable } = require('node:stream');
const plugin = require('../harness/home/profiles/web/plugins/quant-model-settings.js');

function fixture() {
  let handler;
  const calls = [];
  let selection = { provider: 'mock', model: 'one' };
  const services = {
    webServer: { register(route) { handler = route.handler; return () => {}; } },
    settings: {
      describe() { return [{ ns:'agent-default-model', revision:3, value:{...selection, secret:'FAKE_SECRET'} }]; },
      async mutate(ns, ops, revision) {
        calls.push({ ns, ops, revision });
        if (revision !== 3) { const error = new Error('FAKE_SECRET'); error.name = 'SettingsConflictError'; throw error; }
        selection = Object.fromEntries(ops.map(op => [op.path[0], op.value]));
      }
    },
    agentDefaultModel: { currentSelection() { return {...selection, secret:'FAKE_SECRET'}; } }
  };
  plugin.apply({ get(name) { return services[name]; }, effect(fn) { return fn(); } });
  async function request(method='GET', body='', options={}) {
    const req = Readable.from([Buffer.from(body)]);
    req.method = method;
    req.headers = {host:'127.0.0.1:3080',origin:'http://127.0.0.1:3080','x-quant-request':'1','content-type':'application/json',...options.headers};
    req.socket = { remoteAddress:options.peer || '127.0.0.1' };
    const result = { headers:{} };
    await handler(req, { writeHead(status, headers) { result.status=status; result.headers=headers; }, end(value) { result.body=JSON.parse(value); } });
    return result;
  }
  return { request, calls };
}

test('default selection reads and writes only native owned fields', async () => {
  const f = fixture();
  const read = await f.request();
  assert.equal(read.status,200);
  assert.deepEqual(read.body,{ok:true,defaultModel:{provider:'mock',model:'one'},revision:3});
  assert.equal(JSON.stringify(read).includes('FAKE_SECRET'),false);
  const saved = await f.request('POST',JSON.stringify({provider:'other',model:'two',expectedRevision:3}));
  assert.equal(saved.status,200);
  assert.deepEqual(f.calls,[{ns:'agent-default-model',ops:[{op:'set',path:['provider'],value:'other'},{op:'set',path:['model'],value:'two'}],revision:3}]);
  assert.equal(saved.body.defaultModel.provider,'other');
});

test('all reads and writes require loopback peer exact origin and header', async () => {
  for (const method of ['GET','POST']) {
    for (const options of [{peer:'192.168.1.2'}, {headers:{origin:'http://127.0.0.1:9999'}}, {headers:{'x-quant-request':''}}, {headers:{origin:''}}]) {
      const f=fixture();
      assert.equal((await f.request(method,'{}',options)).status,403);
      assert.deepEqual(f.calls,[]);
    }
  }
});

test('conflicts invalid JSON oversized body and unowned fields are safe', async () => {
  for (const [body,status] of [[JSON.stringify({provider:'mock',model:'one',expectedRevision:2}),409],['{',400],['x'.repeat(4097),413],[JSON.stringify({provider:'mock',model:'one',expectedRevision:3,secret:'FAKE_SECRET'}),400]]) {
    const f=fixture();
    const result=await f.request('POST',body);
    assert.equal(result.status,status);
    assert.equal(JSON.stringify(result).includes('FAKE_SECRET'),false);
    assert.equal(result.headers['Access-Control-Allow-Origin'],undefined);
    if(status!==409) assert.deepEqual(f.calls,[]);
  }
});
