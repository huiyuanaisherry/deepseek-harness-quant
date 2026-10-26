const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(path.join(__dirname, '..', 'ui_v2', 'core', 'api.js'), 'utf8');

function ok(data) {
  return {ok: true, status: 200, json: async () => data};
}

function fail(status) {
  return {ok: false, status, json: async () => ({ok: false})};
}

function harness(responder) {
  const calls = [];
  const timers = {created: 0, cleared: 0};
  const win = {location: {assign(url) { win.redirected = url; }}};
  win.fetch = function (url, options) {
    const index = calls.length + 1;
    calls.push({url, options});
    return Promise.resolve(responder(url, options || {}, index));
  };
  class Headers {
    constructor(init) { this.map = Object.assign({}, init || {}); }
    set(key, value) { this.map[String(key).toLowerCase()] = value; }
  }
  const context = vm.createContext({
    window: win,
    Headers,
    AbortController,
    setTimeout(fn, ms) { timers.created += 1; return setTimeout(fn, ms); },
    clearTimeout(id) { timers.cleared += 1; clearTimeout(id); }
  });
  vm.runInContext(SOURCE, context);
  // 页面里 fetch 是全局函数；api.js 在启动时包装了 window.fetch
  context.fetch = win.fetch;
  return {win, calls, timers, api: win.LW.api};
}

test('default get keeps 30s cache and dedupes identical concurrent requests', async () => {
  const env = harness(() => ok({value: 1}));
  const [first, second] = await Promise.all([env.api.get('/api/x'), env.api.get('/api/x')]);
  assert.deepEqual(JSON.parse(JSON.stringify(first)), {value: 1});
  assert.deepEqual(JSON.parse(JSON.stringify(second)), {value: 1});
  assert.equal(env.calls.length, 1);
  await env.api.get('/api/x');
  assert.equal(env.calls.length, 1);
});

test('bypass skips the short cache without changing default behaviour', async () => {
  const env = harness(() => ok({value: 1}));
  await env.api.get('/api/x');
  await env.api.get('/api/x', {bypass: true});
  assert.equal(env.calls.length, 2);
  assert.equal(env.calls[1].options.cache, 'no-store');
});

test('non-strict failure still falls back to labelled stale cache for legacy pages', async () => {
  const env = harness((url, options, index) => index === 1 ? ok({value: 'old'}) : fail(500));
  await env.api.get('/api/x');
  const value = await env.api.get('/api/x', {bypass: true, retry: 0});
  assert.deepEqual(JSON.parse(JSON.stringify(value)), {value: 'old'});
  assert.equal(env.calls.length, 2);
});

test('strict failure never returns stale cache', async () => {
  const env = harness((url, options, index) => index === 1 ? ok({value: 'old'}) : fail(503));
  await env.api.get('/api/x');
  await assert.rejects(env.api.get('/api/x', {bypass: true, strict: true, retry: 0}), /HTTP 503/);
  assert.equal(env.calls.length, 2);
});

test('timeout really aborts the request and clears its timer', async () => {
  let aborted = false;
  const env = harness((url, options) => new Promise((resolve, reject) => {
    if (options.signal) {
      options.signal.addEventListener('abort', () => {
        aborted = true;
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      });
    }
  }));
  await assert.rejects(env.api.get('/api/slow', {timeout: 20, retry: 0, strict: true}), /TIMEOUT/);
  assert.equal(aborted, true);
  assert.equal(env.timers.created, 1);
  assert.equal(env.timers.cleared, 1);
});

test('successful and failed requests both release the timeout timer', async () => {
  const success = harness(() => ok({value: 1}));
  await success.api.get('/api/ok', {retry: 0});
  assert.equal(success.timers.created, 1);
  assert.equal(success.timers.cleared, 1);

  const failure = harness(() => fail(500));
  await assert.rejects(failure.api.get('/api/bad', {retry: 0, strict: true}));
  assert.equal(failure.timers.created, 1);
  assert.equal(failure.timers.cleared, 1);
});

test('unauthorized responses still redirect to login through the shared wrapper', async () => {
  const env = harness(() => fail(401));
  await assert.rejects(env.api.get('/api/protected', {retry: 0, strict: true}));
  assert.equal(env.win.redirected, '/login');
});
