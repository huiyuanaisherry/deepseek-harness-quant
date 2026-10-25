const test = require('node:test');
const assert = require('node:assert/strict');
const {Readable} = require('node:stream');
const plugin = require('../harness/home/profiles/web/plugins/dsq-quant-bridge.js');
function fixture(events) {
 const routes = new Map();
 const received=[];
 const session={events, deriveMessages:() => events.filter(e => /^(user|assistant)\/message$/.test(e.type)).map(e=>e.data)};
 const agent={id:'root',session,followup(m){received.push(m);}};
 const services={webServer:{register(r){routes.set(r.path,r.handler);return ()=>{};}},sessions:{get:()=>session},agents:{get:()=>agent,roots:()=>[agent]},sessionTitle:{get:()=>({title:'Test'})},subagents:{listChildren:async()=>[],startContinuable:async()=>({childId:'child'}),followup:async()=> 'niu-request'}};
 plugin.apply({get:n=>services[n],effect:fn=>fn()});
 return {received,async request(path,body){
  const req=Readable.from(body ? [Buffer.from(JSON.stringify(body))] : []);req.url=path;req.method=body ? 'POST':'GET';
  let result;
  await routes.get(path.split('?')[0])(req,{setHeader(){},writeHead(){},end(s){result=JSON.parse(s);}});
  return result;
 }};
}
const user=(text,source={kind:'user'},id='request-1')=>({type:'user/message',data:{role:'user',id,source,content:[{type:'text',text}]}});
test('chat exposes user/assistant messages but excludes plugin instructions and runtime context',async()=>{
 const f=fixture([user('hello'),user('<system-reminder>PRIVATE INSTRUCTIONS</system-reminder>',{kind:'plugin',plugin:'instructions'}),user('PRIVATE WORKSPACE RULES',{kind:'agent-instructions'}),user('PRIVATE SKILL CATALOG',{kind:'skill-catalog'}),{type:'assistant/message',data:{role:'assistant',content:[{type:'text',text:'connected'}]}}]);
 const r=await f.request('/quant/recent?sessionId=root');
 assert.deepEqual(r.messages.map(m=>m.text),['hello','connected']);
 assert.equal(r.messages[0].id,'request-1');
 assert.equal(JSON.stringify(r).includes('PRIVATE'),false);
});
test('turn failures return bounded safe status without raw error details',async()=>{
 const f=fixture([user('hello'),{type:'turn/start',data:{turn:1}},{type:'turn/end',data:{turn:1,reason:{kind:'error',error:{code:'UNSUPPORTED_REASONING_EFFORT',message:'PRIVATE KEY'}}}}]);
 const r=await f.request('/quant/recent?sessionId=root');
 assert.deepEqual(r.status,{state:'error',code:'UNSUPPORTED_REASONING_EFFORT',requestId:'request-1'});
 assert.equal(JSON.stringify(r).includes('PRIVATE'),false);
 const unknown=fixture([{type:'turn/end',data:{reason:{kind:'error',error:{code:'PRIVATE-SECRET',message:'PRIVATE KEY'}}}}]);
 assert.deepEqual((await unknown.request('/quant/recent?sessionId=root')).status,{state:'error',code:'MODEL_ERROR'});
});
test('running and completed turns remain distinct and each accepted message has an id',async()=>{
 const events=[{type:'turn/start',data:{turn:1}}];const f=fixture(events);
 assert.deepEqual((await f.request('/quant/recent?sessionId=root')).status,{state:'running'});
 events.push({type:'turn/end',data:{reason:{kind:'completed'}}});
 assert.deepEqual((await f.request('/quant/recent?sessionId=root')).status,{state:'idle'});
 const r=await f.request('/quant/chat2',{text:'hello',sessionId:'root'});
 assert.equal(r.accepted,true);assert.ok(r.requestId);assert.equal(f.received[0].id,r.requestId);
});


test('persona chat returns the native followup message id',async()=>{
 const f=fixture([]);
 const r=await f.request('/quant/niu/chat',{persona:'linyuan',text:'hello'});
 assert.equal(r.accepted,true);assert.equal(r.requestId,'niu-request');
});
