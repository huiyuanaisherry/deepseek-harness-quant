/* Token lives only in the password field and the explicit save request. */
(function () {
  'use strict';
  function isDirty(saved, form) {
    return !saved || form.endpoint.trim() !== saved.endpoint || !!form.token || form.allowInsecureHttp !== saved.allowInsecureHttp;
  }
  function payload(saved, form) {
    if (!saved) throw new Error('请先刷新配置。');
    var endpoint = form.endpoint.trim(), url;
    try { url = new URL(endpoint); } catch (_) { throw new Error('请填写完整的 HTTP / HTTPS 接口地址。'); }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('地址仅支持 HTTP / HTTPS，不能包含账号、密码、查询参数或片段。');
    if (url.protocol === 'http:' && !form.allowInsecureHttp) throw new Error('HTTP 会明文传输 Token，请勾选确认。');
    if (!form.token.trim() && (endpoint !== saved.endpoint || !saved.configured)) throw new Error('首次配置或更改目的地址需要输入新的 Token。');
    return {expectedRevision:saved.revision, endpoint:endpoint, token:form.token, allowInsecureHttp:form.allowInsecureHttp};
  }
  var labels = {available:'可用', empty:'返回空数据，尚不能确认权限', credentials:'Token 无效或未配置', permission:'权限不足', rate_limited:'请求频率受限，请稍后再试', network:'网络连接失败', error:'验证失败'};
  function verificationMessage(result, expectedChecks) {
    var checks = result.checks || [];
    var all = checks.length > 0 && checks.every(function (check) { return check.status === 'available'; });
    if (expectedChecks) all = all && expectedChecks.every(function (expected) { return checks.some(function (check) { return check.id === expected.id && check.status === 'available'; }); });
    return {error:!all, message:all ? '本次小样本检查均返回数据；不代表已获得全部接口权限，也不代表数据已下载。' : '本次检查未全部确认可用，请逐项查看结果；空数据不能证明已有权限。'};
  }
  function errorMessage(code) {
    var messages = {revision_conflict:'配置版本已变化，请刷新后重新填写并保存。', conflict:'配置版本已变化，请刷新后重新填写并保存。', verification_busy:'已有验证正在进行，请稍后再试。', busy:'已有验证正在进行，请稍后再试。', cooldown:'验证间隔过短，请稍后再试。', rate_limited:'请求频率受限，请稍后再试。', timeout:'请求超时，请刷新确认已保存状态后重试。', credentials:'Token 未配置或无效，请重新输入。', invalid_endpoint:'接口地址无效，请检查完整地址。', insecure_http:'HTTP 会明文传输 Token，请勾选确认。'};
    code=String(code || '').toLowerCase();
    var aliases={verify_busy:'verification_busy',verify_cooldown:'cooldown',token_required:'credentials',invalid_token:'credentials',insecure_http_confirmation_required:'insecure_http'};
    return messages[aliases[code] || code] || '请求失败，请检查配置或刷新后重试。';
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = {payload:payload,isDirty:isDirty,verificationMessage:verificationMessage,errorMessage:errorMessage}; return; }
  var saved = null, busy = false;
  var $ = function (id) { return document.getElementById(id); };
  function form() { return {endpoint:$('endpoint').value, token:$('token').value, allowInsecureHttp:$('allow-http').checked}; }
  function status(message, error) { $('status').textContent=message; $('status').className=error ? 'status error' : 'status'; }
  function sync() {
    var current=form(), dirty=isDirty(saved,current);
    $('save').disabled=busy || !saved;
    $('refresh').disabled=busy;
    $('verify').disabled=busy || dirty || !saved || !saved.configured;
    ['endpoint','token','allow-http'].forEach(function (id) { $(id).disabled=busy || !saved; });
    $('verify-hint').textContent=dirty ? '有未保存修改，请先保存再验证。' : saved && !saved.configured ? '请先保存 Token，再验证已保存配置。' : '仅验证当前已保存版本；每个接口独立显示结果。';
    $('destination').textContent='Token 发送目标：' + (current.endpoint.trim() || '尚未填写');
    $('http-warning').hidden=!/^http:/i.test(current.endpoint.trim());
  }
  function render(dto) {
    saved=dto; $('endpoint').value=dto.endpoint || dto.defaultEndpoint || '';  $('token').value=''; $('allow-http').checked=!!dto.allowInsecureHttp;
    $('credential-state').textContent=dto.configured ? 'Token 已配置 · 不会回显；同一地址留空保存会保留已有 Token。' : 'Token 未配置 · 请填写 Token。';
    $('test-symbol').textContent='小样本标的：'+dto.testSymbol;
    $('data-mode').textContent=dto.dataMode ? dto.dataMode.note+'（当前目录：'+dto.dataMode.path+'）' : '';
    $('checks').replaceChildren();
    (dto.checks || []).forEach(function (check) { var li=document.createElement('li'); li.textContent=check.label+'：尚未验证'; $('checks').appendChild(li); }); sync();
  }
  async function load() {
    // This API client's fallback cache must not restore an older settings revision.
    LW.api.clear();
    var timer;
    var limit=new Promise(function (_, reject) { timer=setTimeout(function () { reject(new Error(errorMessage('timeout'))); },45000); });
    var dto;
    try { dto=await Promise.race([LW.api.get('/api/data-settings/tushare',{bypass:true,retry:0}),limit]); }
    finally { clearTimeout(timer); }
    if (!dto || dto.ok === false) throw new Error('加载失败，请刷新重试。');
    render(dto);
  }
  async function post(url, body) {
    var controller=new AbortController();
    var timer=setTimeout(function () { controller.abort(); },45000);
    try {
      var response=await fetch(url,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-Quant-Request':'1'},body:JSON.stringify(body),signal:controller.signal});
      if (response.status===401) { location.assign('/login'); throw new Error('登录已过期。'); }
      var result=await response.json();
      if (!response.ok || result.ok!==true) throw new Error(errorMessage(response.status===409 ? 'revision_conflict' : result.code));
      return result;
    } catch (error) {
      if (error.name==='AbortError') throw new Error(errorMessage('timeout'));
      if (error instanceof TypeError || error instanceof SyntaxError) throw new Error('网络请求失败，请刷新确认配置状态后重试。');
      throw error;
    } finally { clearTimeout(timer); }
  }
  async function action(fn) {
    if (busy) return;
    busy=true; sync();
    try { await fn(); } catch (error) { status(error.message,true); }
    finally { busy=false; sync(); }
  }
  ['endpoint','token','allow-http'].forEach(function (id) { $(id).addEventListener(id==='allow-http' ? 'change' : 'input',function () { sync(); $('checks').replaceChildren(); status('有未保存修改，请先保存再验证。'); }); });
  $('settings-form').addEventListener('submit',function (event) { event.preventDefault(); return action(async function () {
    var body=payload(saved,form());
    status('正在保存配置…');
    var result=await post('/api/data-settings/tushare',body);
    render(result); status('配置已保存，Token 输入已清空。保存不会发起验证或下载数据。');
  }); });
  $('verify').addEventListener('click',function () { if (!saved || !saved.configured || isDirty(saved,form())) { sync(); return; } return action(async function () {
    status('正在验证已保存配置，请稍候…');
    var result=await post('/api/data-settings/tushare/verify',{expectedRevision:saved.revision});
    if (result.revision!==saved.revision || result.endpoint!==saved.endpoint) throw new Error('配置版本已变化，请刷新后重新验证。');
    $('checks').replaceChildren();
    (result.checks || []).forEach(function (check) { var li=document.createElement('li'); li.textContent=check.label+'：'+(labels[check.status] || labels.error); $('checks').appendChild(li); });
    var outcome=verificationMessage(result,saved.checks); status(outcome.message,outcome.error);
  }); });
  $('refresh').addEventListener('click',function () { return action(async function () { $('token').value=''; await load(); status('配置已刷新，Token 输入已清空。'); }); });
  // Initial loading uses the same lock as refresh/save so responses cannot race.
  action(async function () {
    await load();
    status('配置已加载。保存和验证分开执行。');
  });
})();
