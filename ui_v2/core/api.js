/* ui_v2/core/api.js — ★统一 API 客户端（UI v2 标准 #18 冗余+数据顺畅）
   功能：8s 超时 + 失败重试 1 次 + 同页缓存（同 URL 只拉一次）+ 60s 轮询（活跃页）
   全局命名空间 LW.api，供所有页面复用——冗余容错（不白屏）的第一道防线。
   用法：
     LW.api.get('/api/live/factors').then(function(d){...})   // 自动缓存+重试
     LW.api.poll('/api/live/factors', 60, renderFn)           // 60s 轮询
*/
(function (win) {
  'use strict';
  var nativeFetch = window.fetch.bind(window);
  window.fetch = function (url, options) {
    options = Object.assign({credentials:'same-origin'}, options || {});
    if (String(options.method || 'GET').toUpperCase() === 'POST') {
      var headers = new Headers(options.headers || {}); headers.set('X-Quant-Request','1');
      options.headers = headers;
    }
    return nativeFetch(url, options).then(function (response) {
      if (response.status === 401) { window.location.assign('/login'); throw new Error('登录已过期'); }
      return response;
    });
  };
  var cache = {};        // url -> {ts, data, status:'ok'|'err'}
  var inflight = {};     // url -> Promise（防并发重复请求）

  function get(url, opts) {
    opts = opts || {};
    var timeout = opts.timeout || 8000;
    var retry = opts.retry !== undefined ? opts.retry : 1;   // 默认重试 1 次
    var bypass = opts.bypass === true;   // 强制刷新（审批/卖出后即时更新用）
    var strict = opts.strict === true;   // 严格模式：失败绝不返回旧缓存（真实观察池等）
    var cached = cache[url];
    var now = Date.now();
    // 同页缓存：30s 内直接复用（页面内多个组件共用一个 API）
    if (!bypass && cached && now - cached.ts < 30000 && cached.status === 'ok') {
      return Promise.resolve(cached.data);
    }
    // 严格/强制刷新不走普通去重，避免拿到别的调用方的降级结果
    var dedupe = !bypass && !strict;
    if (dedupe && inflight[url]) { return inflight[url]; }

    function attempt(remaining) {
      return request(url, timeout).then(function (data) {
        cache[url] = { ts: Date.now(), data: data, status: 'ok' };
        return data;
      }, function (err) {
        // 重试一次（网络抖动）
        if (remaining > 0) { return attempt(remaining - 1); }
        // 重试仍失败：严格模式抛错，其他页面沿用旧缓存（非白屏）
        if (!strict && cached) { cache[url] = { ts: cached.ts, data: cached.data, status: 'err' }; return cached.data; }
        throw err;
      });
    }

    var p = attempt(retry);
    if (dedupe) {
      inflight[url] = p;
      var release = function () { delete inflight[url]; };
      p.then(release, release);
    }
    return p;
  }

  // 单次请求：AbortController 真正中止 + 计时器清理（成功/失败都会清）
  function request(url, timeout) {
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var options = { cache: 'no-store' };
    if (controller) { options.signal = controller.signal; }
    var timer = null;
    return new Promise(function (resolve, reject) {
      timer = setTimeout(function () {
        if (controller) { try { controller.abort(); } catch (e) { /* 已被中止 */ } }
        reject(new Error('TIMEOUT'));
      }, timeout);
      fetch(url, options).then(function (r) {
        if (!r.ok) {
          var error = new Error('HTTP ' + r.status);
          error.status = r.status;
          throw error;
        }
        return r.json();
      }).then(resolve, reject);
    }).then(function (data) {
      clearTimeout(timer); return data;
    }, function (err) {
      clearTimeout(timer); throw err;
    });
  }

  // 轮询：interval 秒拉一次（后台标签页自动降频 5min——省资源）
  function poll(url, intervalSec, renderFn) {
    var tick = function () {
      var hidden = document.hidden;
      var wait = hidden ? 300000 : (intervalSec * 1000);
      get(url).then(renderFn).catch(function () { /* 降级由 get 处理 */ });
      setTimeout(tick, wait);
    };
    tick();
  }

  // 清空缓存（审批/卖出后数据已变，下次 get 强制重拉最新）
  function clear() {
    cache = {};
    inflight = {};
  }

  // POST JSON（审批/卖出/手动更新等写操作——不带缓存、不重试）
  function post(url, body, opts) {
    opts = opts || {};
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Quant-Request':'1' },
      body: JSON.stringify(body || {}),
      cache: 'no-store'
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  win.LW = win.LW || {};
  win.LW.api = { get: get, poll: poll, clear: clear, post: post };
})(window);
