const {test} = require('node:test');
const assert = require('node:assert/strict');

const P = require('../ui_v2/core/portal_status.js');

test('six states have deterministic labels and only ready is green', () => {
  const states = ['ready', 'empty', 'missing', 'stale', 'blocked', 'error'];
  assert.deepEqual(P.STATES, states);
  const labels = states.map(P.stateLabel);
  assert.equal(new Set(labels).size, states.length);
  for (const s of states) assert.ok(P.stateLabel(s).length > 0);
  assert.equal(P.stateTone('ready'), 'ok');
  for (const s of ['missing', 'blocked', 'error', 'empty', 'stale']) {
    assert.notEqual(P.stateTone(s), 'ok', s + ' must not be green');
  }
});

test('legacy payload without modules shows unknown, not normal', () => {
  const view = P.moduleView(undefined, 'opp_pool');
  assert.equal(view.state, 'unknown');
  assert.equal(view.label, '状态未知');
  assert.equal(view.known, false);
  assert.equal(view.showValue, false);
  assert.equal(P.valueText(view, 5), '—');
  assert.equal(P.moduleView({}, 'opp_pool').state, 'unknown');
});

test('missing/blocked/error hide business numbers, empty shows 0', () => {
  for (const state of ['missing', 'blocked', 'error']) {
    const mods = {opp_pool: {state, mode: 'real', data_date: null, generated_at: null,
      scope: 'unknown', reason: 'x', run_id: null}};
    const view = P.moduleView(mods, 'opp_pool');
    assert.equal(view.state, state);
    assert.equal(view.showValue, false);
    assert.equal(P.valueText(view, 0), '—');
    assert.notEqual(P.stateTone(state), 'ok');
  }
  const empty = P.moduleView({opp_pool: {state: 'empty', mode: 'real'}}, 'opp_pool');
  assert.equal(empty.showValue, true);
  assert.equal(P.valueText(empty, 0), '0');
});

test('ready and stale keep values, stale is not green', () => {
  const ready = P.moduleView({pitch: {state: 'ready', mode: 'real'}}, 'pitch');
  assert.equal(P.stateTone('ready'), 'ok');
  assert.equal(P.valueText(ready, 12), '12');
  const stale = P.moduleView({pitch: {state: 'stale', mode: 'real',
    data_date: '2026-10-01', reason: 'artifact_stale'}}, 'pitch');
  assert.equal(P.valueText(stale, 3), '3');
  assert.equal(stale.dataDate, '2026-10-01');
  assert.notEqual(stale.tone, 'ok');
});

test('traffic light always ends loading when state is absent', () => {
  for (const tl of [undefined, null, {}, {label: '观望'}]) {
    const view = P.trafficLightView(tl);
    assert.equal(view.rendered, false);
    assert.equal(view.loading, false);
    assert.equal(view.state, 'unknown');
    assert.ok(view.text.indexOf('暂不可用') >= 0);
  }
  const ok = P.trafficLightView({state: 'greedy', label: '贪婪'});
  assert.equal(ok.rendered, true);
  assert.equal(ok.loading, false);
});

test('request failure and timeout both end loading with explicit text', () => {
  const timeout = P.requestFailure(new Error('TIMEOUT'));
  assert.equal(timeout.loading, false);
  assert.equal(timeout.state, 'error');
  assert.ok(timeout.text.indexOf('超时') >= 0);

  const down = P.requestFailure(new Error('HTTP 502'));
  assert.equal(down.loading, false);
  assert.equal(down.state, 'error');
  assert.ok(down.text.indexOf('不可达') >= 0);
});

test('summary never claims all normal when a module is missing', () => {
  const ready = {state: 'ready', mode: 'real'};
  const all = P.summarize({a: ready, b: ready});
  assert.equal(all.allReady, true);
  assert.equal(all.text, '全部 2 项正常');

  const degraded = P.summarize({a: ready, b: {state: 'missing', mode: 'real'}});
  assert.equal(degraded.allReady, false);
  assert.ok(degraded.text.indexOf('缺失') >= 0);
  assert.notEqual(degraded.text, '全部 2 项正常');

  const legacy = P.summarize(undefined);
  assert.equal(legacy.total, 0);
  assert.equal(legacy.allReady, false);
  assert.equal(legacy.text, '状态未知');
});

test('unknown state from bad payload falls back to unknown', () => {
  const view = P.moduleView({x: {state: 'processing'}}, 'x');
  assert.equal(view.state, 'unknown');
  assert.equal(view.label, '状态未知');
  assert.equal(view.showValue, false);
});

test('reason codes map to deterministic text without leaking raw errors', () => {
  assert.equal(P.reasonText('artifact_invalid_json'), '产物 JSON 已损坏');
  assert.equal(P.reasonText('engine_unavailable'), '缺少计算引擎 pyarrow');
  assert.equal(P.reasonText('scheduler_unsupported'), '当前系统不支持计划任务查询');
  assert.equal(P.reasonText(null), '');
  assert.equal(P.reasonText(''), '');
  assert.equal(P.reasonText('some/path/leak'), '未知原因');
});

test('module note states the reason for unavailable modules', () => {
  const unknown = P.moduleView(undefined, 'opp_pool');
  assert.ok(P.moduleNote(unknown).indexOf('状态未知') >= 0);

  const missing = P.moduleView({
    opp_pool: {state: 'missing', mode: 'real', reason: 'artifact_missing'}
  }, 'opp_pool');
  const missingNote = P.moduleNote(missing);
  assert.ok(missingNote.indexOf('数据缺失') >= 0);
  assert.ok(missingNote.indexOf('产物文件未生成') >= 0);

  const blocked = P.moduleView({
    global_rotation: {state: 'blocked', mode: 'unknown',
      reason: 'engine_unavailable'}
  }, 'global_rotation');
  const blockedNote = P.moduleNote(blocked);
  assert.ok(blockedNote.indexOf('无法计算') >= 0);
  assert.ok(blockedNote.indexOf('pyarrow') >= 0);

  const ready = P.moduleView({
    pitch: {state: 'ready', mode: 'real', data_date: '2026-10-23',
      generated_at: '2026-10-23 18:31:02'}
  }, 'pitch');
  const readyNote = P.moduleNote(ready);
  assert.ok(readyNote.indexOf('正常') >= 0);
  assert.ok(readyNote.indexOf('2026-10-23') >= 0);
  assert.ok(readyNote.indexOf('生成') >= 0);
});
