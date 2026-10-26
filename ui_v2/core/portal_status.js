/* ui_v2/core/portal_status.js — 门户模块六态展示契约（纯函数，无网络/无 DOM）
   用途：把后端 modules[key] 的 {state, mode, data_date, reason...} 映射为前端确定文案。
   原则：
     1. 只有 ready 允许绿色；missing/blocked/error 隐藏业务数值（不得显示 0）。
     2. 旧接口没有 modules 时一律“状态未知”，不得当成正常。
     3. 所有请求失败/超时/缺字段都必须结束“加载中”。
   浏览器挂载：window.LW.portalStatus；Node 测试：module.exports。
*/
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.LW = root.LW || {};
    root.LW.portalStatus = api;
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STATES = ['ready', 'empty', 'missing', 'stale', 'blocked', 'error'];
  var LABELS = {
    ready: '正常',
    empty: '无数据',
    missing: '数据缺失',
    stale: '数据陈旧',
    blocked: '无法计算',
    error: '计算异常',
    unknown: '状态未知'
  };
  var TONES = {
    ready: 'ok',
    empty: 'warn',
    missing: 'bad',
    stale: 'warn',
    blocked: 'bad',
    error: 'bad',
    unknown: 'unknown'
  };
  var VALUE_STATES = {ready: true, empty: true, stale: true};

  function stateLabel(state) {
    return LABELS[state] || LABELS.unknown;
  }

  function stateTone(state) {
    return TONES[state] || TONES.unknown;
  }

  // modules[key] -> 展示视图；缺失或非法 state 一律 unknown（旧接口兼容）
  function moduleView(modules, key) {
    var raw = null;
    if (modules && typeof modules === 'object' &&
        Object.prototype.hasOwnProperty.call(modules, key)) {
      raw = modules[key];
    }
    var state = raw && STATES.indexOf(raw.state) >= 0 ? raw.state : 'unknown';
    return {
      key: key,
      state: state,
      label: stateLabel(state),
      tone: stateTone(state),
      known: state !== 'unknown',
      showValue: VALUE_STATES[state] === true,
      mode: raw && raw.mode ? raw.mode : 'unknown',
      dataDate: raw && raw.data_date ? raw.data_date : null,
      generatedAt: raw && raw.generated_at ? raw.generated_at : null,
      reason: raw && raw.reason ? raw.reason : null,
      scope: raw && raw.scope ? raw.scope : 'unknown',
      raw: raw
    };
  }

  // 数值文本：不可用状态与空值统一显示破折号，绝不把缺失伪装成 0
  function valueText(view, value) {
    if (!view || view.showValue !== true) { return '—'; }
    if (value === null || value === undefined || value === '') { return '—'; }
    if (typeof value === 'number' && !isFinite(value)) { return '—'; }
    return String(value);
  }

  // 择时趋势：缺 state、请求失败、超时都要结束加载并给出原因
  function trafficLightView(tl) {
    if (!tl || !tl.state) {
      return {
        rendered: false,
        loading: false,
        state: 'unknown',
        label: LABELS.unknown,
        text: '择时趋势数据暂不可用'
      };
    }
    return {
      rendered: true,
      loading: false,
      state: String(tl.state),
      label: tl.label ? String(tl.label) : String(tl.state),
      text: tl.label ? String(tl.label) : String(tl.state)
    };
  }

  // 请求异常统一出口：超时与不可达必须区分，且都不再转圈
  function requestFailure(err) {
    var msg = err && err.message ? String(err.message) : '';
    if (msg.toUpperCase().indexOf('TIMEOUT') >= 0) {
      return {loading: false, state: 'error', reason: 'timeout', text: '请求超时，稍后自动重试'};
    }
    return {
      loading: false,
      state: 'error',
      reason: 'unreachable',
      text: '接口不可达' + (msg ? '（' + msg + '）' : '')
    };
  }

  // 首页摘要：只要有一项非 ready 就不得声称“全部正常”
  function summarize(modules) {
    if (!modules || typeof modules !== 'object') {
      return {total: 0, ready: 0, allReady: false, counts: {}, text: LABELS.unknown};
    }
    var keys = Object.keys(modules);
    var counts = {ready: 0, empty: 0, missing: 0, stale: 0, blocked: 0, error: 0, unknown: 0};
    keys.forEach(function (key) {
      var view = moduleView(modules, key);
      counts[view.state] = (counts[view.state] || 0) + 1;
    });
    var total = keys.length;
    if (!total) {
      return {total: 0, ready: 0, allReady: false, counts: counts, text: LABELS.unknown};
    }
    if (counts.ready === total) {
      return {total: total, ready: total, allReady: true, counts: counts, text: '全部 ' + total + ' 项正常'};
    }
    var parts = [];
    if (counts.missing) { parts.push(counts.missing + ' 项数据缺失'); }
    if (counts.blocked) { parts.push(counts.blocked + ' 项无法计算'); }
    if (counts.error) { parts.push(counts.error + ' 项计算异常'); }
    if (counts.stale) { parts.push(counts.stale + ' 项数据陈旧'); }
    if (counts.empty) { parts.push(counts.empty + ' 项无数据'); }
    if (counts.unknown) { parts.push(counts.unknown + ' 项状态未知'); }
    return {
      total: total,
      ready: counts.ready,
      allReady: false,
      counts: counts,
      text: parts.join('、')
    };
  }

  // 原因码 → 确定中文说明（后端只下发安全短代码，不下发路径/异常原文）
  var REASON_TEXT = {
    artifact_missing: '产物文件未生成',
    artifact_dir_missing: '产物目录不存在',
    artifact_not_file: '产物路径不是文件',
    artifact_permission_denied: '产物文件无读取权限',
    artifact_unreadable: '产物文件不可读',
    artifact_invalid_json: '产物 JSON 已损坏',
    artifact_schema_mismatch: '产物结构与预期不符',
    artifact_stale: '产物数据已过期',
    no_items: '当前为空结果',
    coverage_insufficient: '数据覆盖不足，无法计算',
    engine_unavailable: '缺少计算引擎 pyarrow',
    input_missing: '缺少输入文件',
    input_invalid: '输入文件结构或数值无效',
    compute_failed: '计算失败',
    status_probe_failed: '状态探测失败',
    source_missing: '数据源文件未生成',
    source_empty: '数据源文件为空',
    source_corrupt_json: '数据源 JSON 已损坏',
    source_unreadable: '数据源文件不可读',
    source_stale: '数据源已过期',
    source_blocked: '数据源不可用',
    scheduler_unsupported: '当前系统不支持计划任务查询',
    query_failed: '计划任务查询失败',
    no_tasks: '没有已注册的计划任务',
    partial_query_failed: '部分计划任务查询失败',
    invalid_state: '状态值非法',
    invalid_mode: '数据模式非法',
    timeout: '请求超时',
    unreachable: '接口不可达',
    unspecified: '未提供原因'
  };

  function reasonText(code) {
    if (!code) { return ''; }
    return REASON_TEXT[String(code)] || '未知原因';
  }

  // 卡片脚注：状态 + 原因 + 数据日；ready 才展示“生成时间”
  function moduleNote(view) {
    if (!view || view.known !== true) {
      return LABELS.unknown + '：接口未提供模块状态';
    }
    var parts = [view.label];
    if (view.state !== 'ready' && view.reason) {
      var reason = reasonText(view.reason);
      if (reason) { parts.push(reason); }
    }
    if (view.dataDate) { parts.push('数据日 ' + view.dataDate); }
    if (view.state === 'ready' && view.generatedAt) {
      parts.push('生成 ' + view.generatedAt);
    }
    return parts.join(' · ');
  }

  return {
    STATES: STATES,
    stateLabel: stateLabel,
    stateTone: stateTone,
    moduleView: moduleView,
    valueText: valueText,
    trafficLightView: trafficLightView,
    requestFailure: requestFailure,
    summarize: summarize,
    reasonText: reasonText,
    moduleNote: moduleNote
  };
});
