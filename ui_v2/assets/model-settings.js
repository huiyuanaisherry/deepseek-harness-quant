/* DSH remains the only credential and settings store. */
(function (root) {
  'use strict';
  function editable(row) { return !row || !!(row.credential && row.credential.writable && !['env', 'environment'].includes(row.credential.source)); }
  function payload(row, form, revision) {
    var out = {provider: row ? row.id : form.id.trim(), expectedRevision: row ? row.revision : revision};
    if (!row || (row.settingsNs === 'llm-pi-ai' && row.profile && row.profile.api && row.profile.baseURL)) {
      if (!form.api || !form.baseURL || !form.models || !out.provider) throw new Error('请填写服务商 ID、协议、HTTPS 地址和模型 ID。');
      out.api = form.api; out.baseURL = form.baseURL.trim();
      out.models = form.models.split(/[\n,]/).map(function (id) { return id.trim(); }).filter(Boolean).map(function (id) { return {id:id}; });
      if (!out.models.length) throw new Error('至少填写一个模型 ID。');
      if (form.displayName.trim()) out.displayName = form.displayName.trim();
    }
    if (form.apiKey && editable(row)) out.apiKey = form.apiKey;
    return out;
  }
  function saveMessage(result) {
    return result.partial ? '配置已保存，但 Key 写入失败。已刷新版本，请重新输入 Key 后重试；尚未全部成功。' : '保存成功。Key 输入已清空；空白 Key 会保留已有凭据。';
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = {payload:payload, editable:editable, saveMessage:saveMessage}; return; }
  var data, selected = null, busy = false;
  var $ = function (id) { return document.getElementById(id); };
  function status(message, error) { $('status').textContent = message; $('status').className = error ? 'status error' : 'status'; }
  async function request(url, body) {
    var options = {credentials:'same-origin', cache:'no-store'};
    if (body !== undefined) Object.assign(options, {method:'POST', headers:{'Content-Type':'application/json','X-Quant-Request':'1'}, body:JSON.stringify(body)});
    var response = await fetch(url, options);
    if (response.status === 401) { location.assign('/login'); throw new Error('登录已过期。'); }
    var result = await response.json();
    if ((!response.ok || result.ok === false) && !result.partial) throw new Error((result.error || '请求失败') + (result.code ? '（' + result.code + '）' : ''));
    return result;
  }
  function option(select, value, label) { var el = document.createElement('option'); el.value=value; el.textContent=label; select.appendChild(el); }
  function render() {
    selected = data.providers.find(function (p) { return p.id === $('provider').value; }) || null;
    var profile = selected ? selected.profile || {} : {};
    $('custom-fields').hidden = !!selected && !(selected.settingsNs === 'llm-pi-ai' && profile.api && profile.baseURL);
    $('provider-id').value = selected ? selected.id : ''; $('provider-id').readOnly = !!selected;
    $('display-name').value = profile.displayName || (selected && selected.name) || '';
    $('protocol').value = profile.api || (data.protocols[0] || '');
    $('endpoint').value = profile.baseURL || '';
    $('models').value = (profile.models || []).map(function (m) { return m.id; }).join('\n');
    $('key').value = ''; $('key').disabled = !editable(selected);
    $('remove-key').disabled = busy || !selected || !editable(selected) || !selected.credential.configured;
    var credential = selected && selected.credential;
    $('credential-state').textContent = credential ? (credential.configured ? 'Key 已配置' : 'Key 未配置') + ' · 来源：' + (credential.source || '未设置') + ' · ' + (editable(selected) ? '可编辑' : '只读（请在运行环境管理）') : '新建兼容服务商 · Key 将写入 DSH 凭据存储';
    $('destination').textContent = profile.baseURL ? '提示词发送至：' + profile.baseURL : '提示词发送至：DSH 原生服务商端点（由运行时配置决定）';
    $('model').replaceChildren();
    (selected ? selected.models || [] : []).forEach(function (m) { option($('model'), m.id, m.name || m.id); });
    if (selected && data.defaultModel.provider === selected.id) $('model').value = data.defaultModel.model;
    $('set-default').disabled = busy || !$('model').options.length;
    $('model-hint').textContent = $('model').options.length ? '仅使用 DSH 本地模型目录。' : '暂无模型。先保存 Key / 配置，再刷新目录。';
    $('current-default').textContent = '当前新会话默认：' + (data.defaultModel.provider || '未设置') + ' / ' + (data.defaultModel.model || '未设置');
  }
  async function load(keep) {
    var id = data ? (keep || $('provider').value) : keep;
    data = await request('/api/model-settings');
    if (id === undefined) id = data.defaultModel.provider;
    $('provider').replaceChildren(); data.providers.forEach(function (p) { option($('provider'),p.id,p.name); }); option($('provider'),'','＋ 自定义兼容服务商');
    $('protocol').replaceChildren(); data.protocols.forEach(function (p) { option($('protocol'),p,p); });
    if (id !== undefined && Array.from($('provider').options).some(function (p) { return p.value === id; })) $('provider').value=id;
    render();
  }
  async function action(fn) {
    if (busy) return; busy=true;
    document.querySelectorAll('button, select').forEach(function (b) { b.disabled=true; });
    try { await fn(); } catch (error) { status(error.message,true); }
    finally { busy=false; document.querySelectorAll('button, select').forEach(function (b) { b.disabled=false; }); if(data) { $('remove-key').disabled=!selected || !editable(selected) || !selected.credential.configured; $('set-default').disabled=!$('model').options.length; } }
  }
  $('provider').addEventListener('change',function () { render(); status('更改尚未保存。'); });
  $('settings-form').addEventListener('submit',function (event) { event.preventDefault(); action(async function () {
    var body=payload(selected,{id:$('provider-id').value,displayName:$('display-name').value,api:$('protocol').value,baseURL:$('endpoint').value,models:$('models').value,apiKey:$('key').value},data.revision);
    var result=await request('/api/model-settings/provider',body); $('key').value='';
    if (typeof result.revision === 'number') { if (selected) selected.revision=result.revision; if (!selected || selected.settingsNs==='llm-pi-ai') data.revision=result.revision; }
    try { await load(body.provider); } catch(error) { status(saveMessage(result)+' 目录刷新失败：'+error.message,true); return; }
    status(saveMessage(result),!!result.partial);
  }); });
  $('remove-key').onclick=function () { action(async function () { await request('/api/model-settings/key/remove',{provider:selected.id}); await load(selected.id); status('Key 已移除。服务商配置和模型目录保留。'); }); };
  $('set-default').onclick=function () { action(async function () { await request('/api/model-settings/default',{provider:selected.id,model:$('model').value,expectedRevision:data.defaultRevision}); await load(selected.id); status('默认模型已保存，仅对新会话生效；已有会话保持原选择。'); }); };
  $('refresh').onclick=function () { action(async function () { await load(); status('目录已刷新。'); }); };
  $('logout').onclick=function () { action(async function () { await request('/api/auth/logout',{}); location.assign('/login'); }); };
  load().then(function () { status('目录已加载。保存配置不会发起模型调用。'); }).catch(function (error) { status('加载失败：'+error.message,true); });
})(typeof window === 'undefined' ? globalThis : window);
