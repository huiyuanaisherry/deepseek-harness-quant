const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {payload,isDirty,verificationMessage,errorMessage}=require('../ui_v2/assets/data-settings.js');
const saved={ok:true,revision:'r1',endpoint:'https://api.example.com/pro',configured:true,allowInsecureHttp:false,checks:[{id:'daily',label:'日线'}],testSymbol:'000001.SZ'};
const form={endpoint:saved.endpoint,token:'',allowInsecureHttp:false};
test('blank token preserves saved destination; fresh token is only in POST payload',()=>{assert.deepEqual(payload(saved,form),{expectedRevision:'r1',endpoint:saved.endpoint,token:'',allowInsecureHttp:false});assert.equal(payload(saved,{...form,token:'synthetic-token'}).token,'synthetic-token');});
test('changed destination and initial setup require new token',()=>{assert.throws(()=>payload(saved,{...form,endpoint:'https://relay.example.com/pro'}),/新.*Token/);assert.throws(()=>payload({...saved,configured:false},form),/Token/);});
test('HTTP requires explicit consent; reject unsafe URL components and protocols',()=>{assert.throws(()=>payload(saved,{...form,endpoint:'http://relay.example.com',token:'fake'}),/明文.*Token/);assert.equal(payload(saved,{...form,endpoint:'http://relay.example.com',token:'fake',allowInsecureHttp:true}).allowInsecureHttp,true);for(const endpoint of ['ftp://example.com','https://u:p@example.com','https://example.com/?key=x','https://example.com/#x'])assert.throws(()=>payload(saved,{...form,endpoint,token:'fake'}));});
test('all credential, URL and consent edits prevent testing old revision',()=>{assert.equal(isDirty(saved,form),false);for(const change of [{token:'fake'},{endpoint:'https://relay.example.com'},{allowInsecureHttp:true}])assert.equal(isDirty(saved,{...form,...change}),true);assert.equal(isDirty(null,form),true);});
test('partial permissions, empty data and network failures are never described as full success',()=>{for(const status of ['permission','empty','network','credentials','rate_limited','error']){const r=verificationMessage({checks:[{status:'available'},{status}]});assert.equal(r.error,true);assert.match(r.message,/未全部/);}assert.equal(verificationMessage({checks:[]}).error,true);assert.match(verificationMessage({checks:[{status:'available'}]}).message,/不代表.*全部/);assert.match(errorMessage('revision_conflict'),/刷新/);assert.ok(!errorMessage('raw token error').includes('raw token'));});
function harness(options={}){let resolveGet;const initialGet=options.deferGet?new Promise(resolve=>{resolveGet=resolve;}):null;const elements={};for(const id of ['status','settings-form','endpoint','token','allow-http','http-warning','destination','credential-state','save','verify','refresh','verify-hint','checks','test-symbol','data-mode'])elements[id]={value:'',checked:false,disabled:false,hidden:false,textContent:'',className:'',children:[],addEventListener(type,fn){this[type]=fn;},replaceChildren(){this.children=[];},appendChild(el){this.children.push(el);}};const calls=[];let dto={...saved};const context={URL,AbortController,setTimeout,clearTimeout,document:{getElementById:id=>elements[id],createElement:()=>({textContent:''})},location:{assign(){}},LW:{api:{clear(){},get:async(url,opts)=>{calls.push({url,opts});return initialGet || dto;}}},fetch:async(url,opts)=>{calls.push({url,body:JSON.parse(opts.body),headers:opts.headers});dto={...saved,revision:'r2'};return {ok:true,status:200,json:async()=>url.endsWith('/verify')?{ok:true,revision:'r2',endpoint:dto.endpoint,checks:[{id:'daily',label:'日线',status:'available'}]}:dto};}};vm.runInNewContext(fs.readFileSync(require.resolve('../ui_v2/assets/data-settings.js'),'utf8'),context);return {elements,calls,resolveGet};}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('real DOM workflow loads, blocks dirty verification, saves and clears token, verifies saved revision',async()=>{const {elements:e,calls}=harness();await settle();assert.equal(e.endpoint.value,saved.endpoint);assert.equal(e.token.value,'');assert.equal(e.verify.disabled,false);assert.equal(calls[0].opts.bypass,true);assert.equal(calls[0].opts.retry,0);e.token.value='synthetic-token';e.token.input();assert.equal(e.verify.disabled,true);await e['settings-form'].submit({preventDefault(){}});await settle();assert.equal(e.token.value,'');assert.equal(e.verify.disabled,false);assert.equal(calls[1].body.token,'synthetic-token');assert.equal(calls[1].headers['X-Quant-Request'],'1');await e.verify.click();await settle();assert.deepEqual(JSON.parse(JSON.stringify(calls[2].body)),{expectedRevision:'r2'});assert.match(e.status.textContent,/不代表.*全部/);});

test('missing check results cannot claim all samples passed',()=>assert.equal(verificationMessage({checks:[{id:'daily',status:'available'}]},[{id:'daily'},{id:'weekly'}]).error,true));

test('backend safe uppercase codes map to actionable local messages',()=>{assert.match(errorMessage('VERIFY_COOLDOWN'),/稍后/);assert.match(errorMessage('TOKEN_REQUIRED'),/Token/);assert.match(errorMessage('INSECURE_HTTP_CONFIRMATION_REQUIRED'),/明文/);});

test('pending initial GET locks refresh and fields, preventing overlapping revision loads',async()=>{
  const {elements:e,calls,resolveGet}=harness({deferGet:true});
  try {
    assert.equal(e.refresh.disabled,true);
    for(const id of ['endpoint','token','allow-http','save','verify'])assert.equal(e[id].disabled,true);
    await e.refresh.click();
    assert.equal(calls.length,1);
  } finally { resolveGet({...saved}); await settle(); }
  assert.equal(e.refresh.disabled,false);
  assert.equal(e.token.disabled,false);
  assert.equal(e.endpoint.value,saved.endpoint);
  e.token.value='synthetic-new-token';e.token.input();await settle();
  assert.equal(e.token.value,'synthetic-new-token');
  assert.equal(e.verify.disabled,true);
});

test('server data mode is shown and never implies the directory switches',async()=>{
  const {elements:e,resolveGet}=harness({deferGet:true});
  resolveGet({...saved,dataMode:{kind:'demo',path:'data/demo',source:'environment',note:'当前读取演示数据（合成，仅用于界面与流程验证）；保存或验证 Tushare 配置不会切换当前数据目录。'}});await settle();
  assert.match(e['data-mode'].textContent,/演示数据/);
  assert.match(e['data-mode'].textContent,/data\/demo/);
});

test('safe server default fills legacy blank endpoint while requiring explicit save',async()=>{
  const {elements:e,calls,resolveGet}=harness({deferGet:true});
  resolveGet({...saved,endpoint:'',defaultEndpoint:'https://api.tushare.pro'});await settle();
  assert.equal(e.endpoint.value,'https://api.tushare.pro');
  assert.equal(e.verify.disabled,true);
  assert.match(e['verify-hint'].textContent,/先保存/);
  await e['settings-form'].submit({preventDefault(){}});await settle();
  assert.equal(calls.length,1);
  assert.match(e.status.textContent,/新的 Token/);
});
