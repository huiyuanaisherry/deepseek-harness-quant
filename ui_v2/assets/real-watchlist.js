/* 真实观察池：只读小样本历史快照。所有数据来自 /api/real-watchlist*，
   不在前端重算策略、不推断数据来源，也不用旧响应覆盖当前选择。 */
(function () {
  'use strict';
  function isBlank(value) {
    return value === null || value === undefined || (typeof value === 'string' && value.trim() === '');
  }
  function finite(value) {
    if (isBlank(value)) return null;
    var number = Number(value);
    return isFinite(number) ? number : null;
  }
  function formatCell(value, digits) {
    var number = finite(value);
    if (number === null) return '暂无';
    return number.toFixed(digits === undefined ? 2 : digits);
  }
  function formatPct(value) {
    var number = finite(value);
    if (number === null) return '暂无';
    return (number > 0 ? '+' : '') + number.toFixed(2) + '%';
  }
  /* 单位来自服务端字段元数据：percent 是小数比例（0.12 → 12.00%），
     index（RSI）已是 0–100，不再乘 100；缺失不能伪装成 0。 */
  function formatFactor(value, unit) {
    var number = finite(value);
    if (number === null) return '暂无';
    if (unit === 'bool') return number ? '是' : '否';
    if (unit === 'percent') return (number * 100).toFixed(2) + '%';
    return number.toFixed(2);
  }
  function chartModel(bars) {
    var list = (bars || []).filter(function (bar) {
      return bar && typeof bar.date === 'string';
    });
    if (!list.length) return {paths: [], volumes: [], min: null, max: null, count: 0, width: 640, height: 258};
    var closes = list.map(function (bar) { return finite(bar.close); });
    var volumes = list.map(function (bar) { return finite(bar.volume); });
    var known = closes.filter(function (value) { return value !== null; });
    if (!known.length) return {paths: [], volumes: [], min: null, max: null, count: list.length, width: 640, height: 258};
    var min = Math.min.apply(null, known);
    var max = Math.max.apply(null, known);
    var scaleMin = min, scaleMax = max;
    if (scaleMax === scaleMin) { scaleMin = min - 1; scaleMax = max + 1; }
    var width = 640, priceTop = 14, priceBottom = 180, pad = 18;
    var count = list.length;
    var step = count > 1 ? (width - pad * 2) / (count - 1) : 0;
    function x(index) { return count === 1 ? width / 2 : pad + step * index; }
    function y(value) { return priceBottom - ((value - scaleMin) / (scaleMax - scaleMin)) * (priceBottom - priceTop); }
    var segments = [], current = [];
    closes.forEach(function (value, index) {
      if (value === null) {
        if (current.length) segments.push(current);
        current = [];
        return;
      }
      current.push([x(index), y(value)]);
    });
    if (current.length) segments.push(current);
    var paths = segments.map(function (segment) {
      return segment.map(function (point, idx) {
        return (idx ? 'L' : 'M') + point[0].toFixed(2) + ' ' + point[1].toFixed(2);
      }).join(' ');
    });
    var knownVolumes = volumes.filter(function (value) { return value !== null; });
    var volumeMax = knownVolumes.length ? Math.max.apply(null, knownVolumes) : 0;
    if (!(volumeMax > 0)) volumeMax = 1;
    var barWidth = Math.max(1, step * 0.6);
    var volumeBars = [];
    volumes.forEach(function (value, index) {
      if (value === null) return;
      var height = Math.max(1, (value / volumeMax) * 48);
      volumeBars.push({
        x: (x(index) - barWidth / 2).toFixed(2),
        y: (238 - height).toFixed(2),
        height: height.toFixed(2),
        width: barWidth.toFixed(2)
      });
    });
    return {paths: paths, volumes: volumeBars, min: min, max: max, count: count, width: width, height: 258};
  }
  function errorMessage(error) {
    var status = error && error.status;
    var code = error && error.code;
    if (status === 409 || code === 'SNAPSHOT_CHANGED') return '快照正在更新，请稍后刷新。';
    if (status === 404 || code === 'NOT_FOUND') return '该股票不在真实观察池名单中，请刷新后重试。';
    if (status === 400 || code === 'INVALID_ADJUST') return '仅支持未复权或前复权。';
    if (status === 503 || code === 'SAMPLE_UNAVAILABLE') return '真实快照尚未生成或暂不可用，请稍后刷新。';
    if (error && error.message === 'TIMEOUT') return '请求超时，请重试。';
    return '网络请求失败，请检查连接后重试。';
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {formatCell: formatCell, formatPct: formatPct, formatFactor: formatFactor,
                      chartModel: chartModel, errorMessage: errorMessage};
    return;
  }

  var FINANCE_FIELDS = [
    ['end_date', '报告期'], ['ann_date', '披露日'], ['eps', 'EPS'], ['roe', 'ROE'],
    ['netprofit_yoy', '净利润同比'], ['or_yoy', '营收同比'], ['grossprofit_margin', '毛利率'],
    ['debt_to_assets', '资产负债率'], ['ocfps', '每股经营现金流'], ['revenue_ps', '每股营收']
  ];
  var ADJUSTS = {none: '未复权', qfq: '前复权'};
  var state = {
    revision: null, stocks: [], source: null, code: null, adjust: 'none',
    listSeq: 0, detailSeq: 0, contextSeq: 0, snapshotRetries: 0, retry: null
  };

  function $(id) { return document.getElementById(id); }
  function text(id, value) { var node = $(id); if (node) node.textContent = value === null || value === undefined ? '' : String(value); }
  function make(tag, className, content) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = String(content);
    return node;
  }
  function setStatus(message, kind) {
    var node = $('wl-status');
    if (!node) return;
    node.textContent = message;
    node.className = 'wl-status' + (kind ? ' ' + kind : '');
  }
  function showRetry(handler) {
    var node = $('wl-retry');
    state.retry = handler;
    if (node) node.hidden = !handler;
  }
  function showDetailMessage(message) {
    text('wl-detail-empty', message);
    var empty = $('wl-detail-empty'), body = $('wl-detail-body');
    if (empty) empty.hidden = false;
    if (body) body.hidden = true;
  }
  function findStock(code) {
    for (var i = 0; i < state.stocks.length; i++) {
      if (state.stocks[i] && state.stocks[i].code === code) return state.stocks[i];
    }
    return null;
  }
  function stockLabel(stock) {
    if (!stock) return '—';
    return (stock.name || stock.code || '—') + '  ' + (stock.code || '');
  }

  function renderContext(context) {
    var page = (context && context.page) || {};
    var main = (context && context.main) || {};
    var watch = (context && context.watchlist) || {};
    text('wl-title', page.title || '真实观察池');
    text('wl-eyebrow', page.eyebrow || 'WORKSPACE / REAL WATCHLIST');
    text('wl-main-source', main.label || '主系统数据模式未知');
    text('wl-main-note', main.note || '无法读取主系统数据配置，不能判定当前数据来源，也不默认为真实数据。');
    var card = $('wl-main-card');
    if (card) card.setAttribute('data-mode', main.mode === 'demo' || main.mode === 'cache' ? main.mode : 'unknown');
    var notes = $('wl-notes');
    if (notes) {
      notes.replaceChildren();
      (watch.notes || []).forEach(function (note) { notes.appendChild(make('li', null, note)); });
      if (!(watch.notes || []).length) notes.appendChild(make('li', null, '历史快照，非实时行情'));
    }
  }

  function renderScope(dto) {
    var scope = dto.scope || {};
    var parts = [];
    if (scope.symbols) parts.push(scope.symbols + ' 只样本');
    if (scope.bars !== null && scope.bars !== undefined) parts.push(scope.bars + ' 条行情');
    if (scope.financeRows !== null && scope.financeRows !== undefined) parts.push(scope.financeRows + ' 条财务');
    if (scope.latestDate) parts.push('最新交易日 ' + scope.latestDate);
    if (dto.verification && dto.verification.status) {
      parts.push(dto.verification.status === 'passed' ? '采集校验通过' : '采集校验未全部通过');
    }
    text('wl-scope', parts.length ? parts.join(' · ') : '小样本历史快照');
  }

  function renderList() {
    var list = $('wl-list');
    if (!list) return;
    var input = $('wl-search');
    var query = String((input && input.value) || '').trim().toLowerCase();
    var items = state.stocks.filter(function (stock) {
      var haystack = ((stock.name || '') + ' ' + (stock.code || '') + ' ' + (stock.industry || '')).toLowerCase();
      return !query || haystack.indexOf(query) >= 0;
    });
    list.replaceChildren();
    text('wl-list-meta', state.stocks.length ? '共 ' + state.stocks.length + ' 只 · 显示 ' + items.length + ' 只' : '');
    if (!items.length) {
      var empty = make('div', 'lw-empty');
      empty.appendChild(make('b', null, state.stocks.length ? '没有匹配的股票' : '观察池暂无股票'));
      empty.appendChild(make('span', null, state.stocks.length ? '请调整搜索关键词。' : '真实快照尚未生成或名单不可用。'));
      list.appendChild(empty);
      return;
    }
    items.forEach(function (stock) {
      var button = make('button', 'wl-item' + (stock.code === state.code ? ' active' : ''));
      button.setAttribute('type', 'button');
      button.setAttribute('data-code', stock.code || '');
      var top = make('div', 'wl-item-top');
      top.appendChild(make('span', 'wl-item-name', stock.name || stock.code || '—'));
      top.appendChild(make('span', 'wl-item-code', stock.code || ''));
      var bottom = make('div', 'wl-item-bot');
      var left = make('span', 'wl-item-price', '未复权 ' + formatCell(stock.close_unadjusted));
      left.appendChild(make('span', 'wl-item-pct ' + (finite(stock.pct_chg) > 0 ? 'wl-up' : finite(stock.pct_chg) < 0 ? 'wl-down' : ''), '  ' + formatPct(stock.pct_chg)));
      bottom.appendChild(left);
      bottom.appendChild(make('span', null, stock.latest_date || '日期暂无'));
      button.appendChild(top);
      button.appendChild(bottom);
      var meta = make('div', 'wl-item-bot');
      meta.appendChild(make('span', null, stock.industry || '行业暂无'));
      meta.appendChild(make('span', 'wl-pill ' + (stock.status === 'ok' ? 'ok' : 'fail'), stock.status === 'ok' ? '校验通过' : '校验未通过'));
      button.appendChild(meta);
      button.addEventListener('click', function () { selectStock(stock.code); });
      list.appendChild(button);
    });
  }

  function preferredCode() {
    var passed = null, withData = null;
    state.stocks.forEach(function (stock) {
      if (!stock || !stock.code) return;
      if (!passed && stock.status === 'ok') passed = stock.code;
      if (!withData && stock.latest_date) withData = stock.code;
    });
    return passed || withData || (state.stocks[0] && state.stocks[0].code) || null;
  }

  function renderListStatus() {
    if (!state.stocks.length) {
      setStatus('观察池暂无可用股票。真实快照尚未生成或名单不可用。', 'warn');
      return;
    }
    var ok = state.stocks.filter(function (stock) { return stock.status === 'ok'; }).length;
    var failed = state.stocks.length - ok;
    var asOf = (state.source && state.source.asOf) || '未知';
    if (failed) {
      setStatus('已加载 ' + state.stocks.length + ' 只样本，其中 ' + ok + ' 只校验通过、' + failed +
                ' 只未通过或缺少行情；数据截至 ' + asOf + '。未通过部分不可用于策略。', 'warn');
    } else {
      setStatus('已加载 ' + state.stocks.length + ' 只样本 · 数据截至 ' + asOf + '。历史快照，非实时行情。', 'ok');
    }
  }

  function renderSource(source) {
    if (!source) return;
    text('wl-source-label', source.label || '此页：真实历史快照 · 小样本观察池');
    text('wl-source-asof', source.asOf ? '实际截至 ' + source.asOf : '实际截至日未知');
  }

  function clearDetail() {
    text('wl-chart-caption', '');
    text('wl-bars-meta', '');
    text('wl-finance-meta', '');
    text('wl-tech-meta', '');
    text('wl-verify', '');
    text('wl-detail-status', '');
    var chart = $('wl-chart');
    if (chart) chart.innerHTML = '';
    ['wl-bars-body', 'wl-finance-body', 'wl-tech-body', 'wl-blockers'].forEach(function (id) {
      var node = $(id);
      if (node) node.replaceChildren();
    });
  }

  function beginDetail(code, adjust) {
    var stock = findStock(code);
    text('wl-stock-title', stockLabel(stock || {code: code}));
    text('wl-stock-meta', '正在读取' + (ADJUSTS[adjust] || '') + '行情…');
    text('wl-detail-status', '正在读取 ' + code + ' 的' + (ADJUSTS[adjust] || '') + '行情…');
    clearDetail();
    var empty = $('wl-detail-empty'), body = $('wl-detail-body');
    if (empty) empty.hidden = true;
    if (body) body.hidden = false;
    syncAdjust(adjust);
  }

  function syncAdjust(adjust) {
    [['wl-adjust-none', 'none'], ['wl-adjust-qfq', 'qfq']].forEach(function (pair) {
      var node = $(pair[0]);
      if (!node) return;
      var active = pair[1] === adjust;
      node.className = active ? 'active' : '';
      node.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function renderChart(dto) {
    var bars = dto.bars || [];
    var model = chartModel(bars);
    var chart = $('wl-chart');
    if (!chart) return;
    if (!model.paths.length) {
      chart.innerHTML = '';
      text('wl-chart-caption', '暂无可用收盘价，无法绘制走势；请查看下方行情明细。');
      return;
    }
    var adjustLabel = (dto.adjust && dto.adjust.label) || ADJUSTS[dto.adjust && dto.adjust.value] || '未复权';
    var svg = '<svg viewBox="0 0 ' + model.width + ' ' + model.height + '" role="img">';
    svg += '<line x1="18" y1="180" x2="622" y2="180" stroke="#2a2a30" stroke-width="1"/>';
    svg += '<line x1="18" y1="14" x2="622" y2="14" stroke="#222228" stroke-width="1"/>';
    svg += '<text x="18" y="10" fill="#8b8b95" font-size="10">' + formatCell(model.max) + '</text>';
    svg += '<text x="18" y="196" fill="#8b8b95" font-size="10">' + formatCell(model.min) + '</text>';
    model.paths.forEach(function (path) {
      svg += '<path d="' + path + '" fill="none" stroke="#8b93ff" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>';
    });
    model.volumes.forEach(function (bar) {
      svg += '<rect x="' + bar.x + '" y="' + bar.y + '" width="' + bar.width + '" height="' + bar.height + '" fill="rgba(94,106,210,.45)"/>';
    });
    svg += '</svg>';
    chart.innerHTML = svg;
    var first = bars[0] && bars[0].date, last = bars[bars.length - 1] && bars[bars.length - 1].date;
    var units = dto.units || {};
    text('wl-chart-caption', '收盘走势 · ' + adjustLabel + ' · ' + (first || '—') + ' 至 ' + (last || '—') +
         ' · 共 ' + model.count + ' 个交易日；下方为成交量（' + (units.volume || '股') + '）。');
  }

  function appendRow(body, values, format) {
    var tr = document.createElement('tr');
    values.forEach(function (value, index) {
      var td = document.createElement('td');
      td.textContent = format ? format(value, index) : (value === null || value === undefined || value === '' ? '暂无' : String(value));
      tr.appendChild(td);
    });
    body.appendChild(tr);
  }

  function renderBars(dto) {
    var body = $('wl-bars-body');
    if (!body) return;
    body.replaceChildren();
    var units = dto.units || {};
    (dto.bars || []).forEach(function (bar) {
      var turn = formatCell(bar.turn);
      appendRow(body, [bar.date, formatCell(bar.open), formatCell(bar.high), formatCell(bar.low),
                       formatCell(bar.close), formatCell(bar.volume, 0), formatCell(bar.amount, 0),
                       formatPct(bar.pct_chg), turn === '暂无' ? turn : turn + '%']);
    });
    if (!(dto.bars || []).length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.setAttribute('colspan', '9');
      td.textContent = '暂无行情明细。';
      tr.appendChild(td);
      body.appendChild(tr);
    }
    text('wl-bars-meta', ((dto.adjust && dto.adjust.label) || '未复权') + ' · 返回 ' + (dto.barsReturned || 0) +
         ' / 共 ' + (dto.barsTotal || 0) + ' 条' + (dto.barsTruncated ? '（已截断）' : '') +
         ' · 价格单位 ' + (units.price || '元') + '，成交量 ' + (units.volume || '股') +
         '，成交额 ' + (units.amount || '元'));
  }

  function renderFinance(dto) {
    var body = $('wl-finance-body');
    var finance = dto.finance || {};
    if (!body) return;
    body.replaceChildren();
    if (!finance.available) {
      text('wl-finance-meta', '暂无：' + (finance.note || '供应商财务文件缺失或为空。'));
      return;
    }
    (finance.rows || []).forEach(function (row) {
      appendRow(body, FINANCE_FIELDS.map(function (field) {
        var value = row[field[0]];
        return field[0] === 'end_date' || field[0] === 'ann_date' ? value : formatCell(value);
      }));
    });
    text('wl-finance-meta', '共 ' + (finance.rowCount || 0) + ' 条 · ' + (finance.note || '原始财务指标，未经验证。'));
  }

  function renderTechnical(dto) {
    var body = $('wl-tech-body');
    var technical = dto.technical || {};
    var blockers = $('wl-blockers');
    if (body) body.replaceChildren();
    if (blockers) blockers.replaceChildren();
    if (!technical.available) {
      text('wl-tech-meta', '暂无：技术指标尚未生成（' + (technical.status || 'unavailable') + '）。');
    } else {
      var fields = technical.fields || {};
      var factors = technical.factors || {};
      Object.keys(fields).forEach(function (key) {
        var tr = document.createElement('tr');
        var name = document.createElement('td');
        name.textContent = fields[key].label || key;
        var value = document.createElement('td');
        value.textContent = formatFactor(factors[key], fields[key].unit);
        tr.appendChild(name);
        tr.appendChild(value);
        if (body) body.appendChild(tr);
      });
      text('wl-tech-meta', technical.note || '仅展示样本已生成的技术指标。');
    }
    var list = technical.blockers || [];
    if (blockers) {
      if (!list.length) blockers.appendChild(make('li', null, '暂无阻塞项记录。'));
      list.forEach(function (item) { blockers.appendChild(make('li', null, item)); });
    }
  }

  function renderVerification(dto) {
    var check = dto.verification || {};
    var repeat = check.repeatWriteReadback === true ? '通过' : check.repeatWriteReadback === false ? '失败' : '暂无';
    text('wl-verify', '校验状态：' + (check.status === 'passed' ? '通过' : '未通过') +
         ' · 幂等复写读回：' + repeat +
         ' · 停牌证据：' + (check.suspensionEvidenceDays === undefined ? '暂无' : check.suspensionEvidenceDays) + ' 天' +
         ' · 缺失日期：' + (check.missingDateCount === undefined ? '暂无' : check.missingDateCount) + ' 天' +
         ' · 演示库未变：' + (check.demoUnchanged ? '是' : '否'));
  }

  function renderDetail(dto) {
    var stock = dto.stock || {};
    var adjust = dto.adjust || {};
    text('wl-stock-title', stockLabel(stock));
    var meta = [];
    if (stock.industry) meta.push('行业 ' + stock.industry);
    if (stock.listDate) meta.push('上市 ' + stock.listDate);
    meta.push('最新交易日 ' + (stock.latestDate || '暂无'));
    meta.push('覆盖 ' + (stock.historyCount === undefined ? '暂无' : stock.historyCount) + ' 个交易日');
    meta.push('校验 ' + (stock.verificationStatus === 'passed' ? '通过' : '未通过'));
    text('wl-stock-meta', meta.join(' · '));
    text('wl-detail-status', '只读快照 · 版本 ' + dto.revision + ' · 切换口径不会触发下载。');
    syncAdjust(adjust.value);
    renderChart(dto);
    renderBars(dto);
    renderFinance(dto);
    renderTechnical(dto);
    renderVerification(dto);
    var empty = $('wl-detail-empty'), body = $('wl-detail-body');
    if (empty) empty.hidden = true;
    if (body) body.hidden = false;
  }

  function loadDetail() {
    if (!state.code || !findStock(state.code)) {
      showDetailMessage('观察池暂无可用股票。');
      return;
    }
    var seq = ++state.detailSeq;
    var code = state.code, adjust = state.adjust, revision = state.revision;
    showRetry(null);
    setStatus('正在读取所选股票详情…');
    beginDetail(code, adjust);
    var url = '/api/real-watchlist/stocks/' + encodeURIComponent(code) +
              '?adjust=' + encodeURIComponent(adjust) +
              (revision ? '&revision=' + encodeURIComponent(revision) : '');
    LW.api.get(url, {strict: true, retry: 0, bypass: true, timeout: 30000}).then(function (dto) {
      if (seq !== state.detailSeq || code !== state.code || adjust !== state.adjust ||
          revision !== state.revision || !findStock(code)) return;
      if (!dto || dto.ok !== true || !dto.stock || dto.stock.code !== code ||
          !dto.adjust || dto.adjust.value !== adjust) {
        throw new Error('BAD_RESPONSE');
      }
      if (revision && dto.revision !== revision) return reloadSnapshot('快照已更新，正在重新加载。');
      state.snapshotRetries = 0;
      renderDetail(dto);
      renderListStatus();
      showRetry(null);
    }).catch(function (error) {
      if (seq !== state.detailSeq || code !== state.code || adjust !== state.adjust ||
          revision !== state.revision || !findStock(code)) return;
      if (error && error.status === 409) {
        if (reloadSnapshot('快照正在更新，正在重新加载。')) return;
      }
      var message = errorMessage(error);
      text('wl-detail-status', message);
      text('wl-stock-meta', '读取失败，旧内容已清除。');
      clearDetail();
      showDetailMessage(message);
      setStatus(message, 'error');
      showRetry(function () { refresh(); });
    });
  }

  function reloadSnapshot(message) {
    if (state.snapshotRetries >= 1) {
      setStatus('快照正在更新，请稍后刷新。', 'warn');
      showDetailMessage('快照正在更新，请稍后刷新。');
      showRetry(function () { refresh(); });
      return false;
    }
    state.snapshotRetries += 1;
    setStatus(message || '快照已更新，正在重新加载。', 'warn');
    loadList(true);
    return true;
  }

  function selectStock(code, force) {
    if (!code) return;
    if (state.code === code && !force) return;
    state.code = code;
    state.snapshotRetries = 0;
    renderList();
    loadDetail();
  }

  function loadContext(force) {
    var seq = ++state.contextSeq;
    return LW.api.get('/api/data-context', {strict: true, retry: 0, bypass: !!force, timeout: 6000}).then(function (context) {
      if (seq !== state.contextSeq) return;
      if (!context || context.ok !== true) throw new Error('BAD_RESPONSE');
      renderContext(context);
    }).catch(function () {
      if (seq !== state.contextSeq) return;
      text('wl-main-source', '主系统数据模式未知');
      text('wl-main-note', '无法读取主系统数据配置，不能判定当前数据来源，也不默认为真实数据。');
      var card = $('wl-main-card');
      if (card) card.setAttribute('data-mode', 'unknown');
    });
  }

  function loadList(force) {
    var seq = ++state.listSeq;
    state.detailSeq += 1;
    state.stocks = [];
    state.revision = null;
    renderList();
    clearDetail();
    text('wl-stock-title', '');
    text('wl-stock-meta', '');
    showDetailMessage('正在读取观察池列表，旧详情已清除。');
    text('wl-source-label', '此页：真实历史快照正在读取');
    text('wl-source-asof', '实际截至日待确认');
    text('wl-scope', '样本范围待确认');
    setStatus(force ? '正在刷新观察池数据…' : '正在加载观察池数据…');
    showRetry(null);
    var options = force ? {strict: true, retry: 0, bypass: true, timeout: 15000}
                        : {strict: true, retry: 0, timeout: 15000};
    return LW.api.get('/api/real-watchlist', options).then(function (dto) {
      if (seq !== state.listSeq) return null;
      if (!dto || dto.ok !== true || !Array.isArray(dto.stocks)) throw new Error('BAD_RESPONSE');
      state.revision = dto.revision;
      state.stocks = dto.stocks;
      state.source = dto.source || null;
      renderSource(state.source);
      renderScope(dto);
      renderListStatus();
      if (!findStock(state.code)) {
        state.code = preferredCode();
      }
      renderList();
      if (state.code) loadDetail();
      else showDetailMessage('观察池暂无可用股票。');
      return dto;
    }).catch(function (error) {
      if (seq !== state.listSeq) return null;
      if (error && error.status === 409 && reloadSnapshot('快照正在更新，正在重新加载列表。')) return null;
      var message = errorMessage(error);
      state.stocks = [];
      state.source = null;
      state.code = null;
      state.revision = null;
      state.detailSeq += 1;
      renderList();
      text('wl-source-label', '此页：真实历史快照不可用');
      text('wl-source-asof', '实际截至日未知');
      text('wl-scope', '样本范围不可用');
      setStatus(message, 'error');
      showDetailMessage(message);
      showRetry(function () { refresh(); });
      return null;
    });
  }

  function refresh() {
    state.snapshotRetries = 0;
    showRetry(null);
    loadContext(true);
    loadList(true);
  }

  function init() {
    var refreshBtn = $('wl-refresh');
    if (refreshBtn) refreshBtn.addEventListener('click', refresh);
    var retryBtn = $('wl-retry');
    if (retryBtn) retryBtn.addEventListener('click', function () {
      var handler = state.retry;
      if (typeof handler === 'function') handler();
    });
    var search = $('wl-search');
    if (search) search.addEventListener('input', renderList);
    [['wl-adjust-none', 'none'], ['wl-adjust-qfq', 'qfq']].forEach(function (pair) {
      var node = $(pair[0]);
      if (!node) return;
      node.addEventListener('click', function () {
        if (!state.code || state.adjust === pair[1]) return;
        state.adjust = pair[1];
        state.snapshotRetries = 0;
        syncAdjust(pair[1]);
        loadDetail();
      });
    });
    loadContext();
    loadList(false);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
