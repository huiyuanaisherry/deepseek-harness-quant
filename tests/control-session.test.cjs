const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function fixture(options = {}) {
  const html = fs.readFileSync('ui_v2/pages/control.html', 'utf8');
  const script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]).find(s => s.includes('function loadSessions()'));
  const elements = new Map();
  for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) elements.set(id, {value:'',textContent:'',innerHTML:'',style:{},querySelectorAll:() => [],addEventListener(){}});
  elements.get('hz-conn-txt').textContent = '连接中…';
  let created = false;
  let releaseCreate;
  const creationGate = options.deferCreate ? new Promise(resolve => {releaseCreate=resolve;}) : Promise.resolve();
  const calls = [];
  const context = {
    document:{getElementById:id => elements.get(id) || null,querySelectorAll:() => []},
    LW:{sidebar:{render(){}},render:{},api:{get:() => new Promise(() => {})}},
    AbortController, setTimeout:() => 1,clearTimeout(){},setInterval(){},clearInterval(){},
    alert:message => { throw new Error(message); },
    fetch:async (path, init = {}) => {
      calls.push({path,init});
      let data = {};
      if (path === '/api/chat/session') {
        if (options.failCreate) return {ok:false,status:502,json:async () => ({ok:false,error:'Upstream error'})};
        await creationGate;
        created = true; data = {ok:true,sessionId:'empty-root'};
      } else if (path.includes('quantapi/sessions')) data = {ok:true,sessions:created || options.existing ? [{id:'empty-root',title:'新会话',preview:'',role:''}] : []};
      else if (path.includes('niuapi/sessions')) data = {ok:true,personas:[]};
      else if (path.includes('/recent')) data = {ok:true,messages:[]};
      return {ok:true,status:200,json:async () => data};
    }
  };
  vm.runInNewContext(script, context);
  const flush = async () => { for(let i=0;i<20;i++) await Promise.resolve(); };
  await flush();
  return {elements,calls,flush,releaseCreate};
}

test('empty runtime reports connected and offers a usable new-session action', async () => {
  const f = await fixture();
  assert.equal(f.elements.get('hz-conn-txt').textContent,'已连接');
  assert.match(f.elements.get('hz-msgs').innerHTML,/新建会话/);
  const button = f.elements.get('hz-new-session');
  assert.ok(button, 'new-session button exists');
  await button.onclick(); await f.flush();
  const call = f.calls.find(c => c.path === '/api/chat/session');
  assert.equal(call.init.method,'POST');
  assert.equal(call.init.headers['X-Quant-Request'],'1');
  assert.equal(call.init.body,'{}');
  assert.match(f.elements.get('hz-sess-list').innerHTML,/empty-root/);
  assert.match(f.elements.get('hz-msgs').innerHTML,/会话为空/);
  assert.equal(f.calls.some(c => /chat2|niuapi\/chat/.test(c.path)),false);
});

test('blank existing roots remain selectable and creation failure is explicit', async () => {
  const f = await fixture({existing:true,failCreate:true});
  assert.match(f.elements.get('hz-sess-list').innerHTML,/empty-root/);
  await f.elements.get('hz-new-session').onclick(); await f.flush();
  assert.match(f.elements.get('hz-chat-status').textContent,/创建失败/);
  assert.equal(f.elements.get('hz-new-session').disabled,false);
});


test('sending cannot race a pending session creation', async () => {
  const f = await fixture({existing:true,deferCreate:true});
  const creation = f.elements.get('hz-new-session').onclick();
  f.elements.get('hz-input').value = 'test message';
  f.elements.get('hz-send').onclick();
  await f.flush();
  assert.equal(f.calls.some(c => /chat2|niuapi\/chat/.test(c.path)),false);
  assert.equal(f.elements.get('hz-input').value,'test message');
  f.releaseCreate(); await creation; await f.flush();
  assert.equal(f.elements.get('hz-new-session').disabled,false);
});
