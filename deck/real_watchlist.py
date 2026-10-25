"""Read-only projection of the verified private real-data sample.

Only the configured sample roster is reachable. SQLite is opened with mode=ro,
every path is confined to data/real-smoke, and responses are whitelisted DTOs.
This module never constructs DailyCache, never creates files and never calls a
data provider, model or collection job.
"""
import csv
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from data.cache import normalize_units
from data.sample_strategy_check import BLOCKERS as STRATEGY_BLOCKERS
from data.sample_strategy_check import TECHNICAL

ROOT = Path(__file__).resolve().parents[1]
CODE_RE = re.compile(r'^\d{6}\.(SZ|SH|BJ)$')
ADJUST_LABELS = {'none': '未复权', 'qfq': '前复权（快照最新因子基准，非实时）'}
BAR_COLUMNS = ('date', 'open', 'high', 'low', 'close', 'preclose', 'volume',
               'amount', 'turn', 'pct_chg', 'source')
FINANCE_COLUMNS = ('end_date', 'ann_date', 'eps', 'roe', 'netprofit_yoy', 'or_yoy',
                   'grossprofit_margin', 'debt_to_assets', 'ocfps', 'revenue_ps')
DEFAULT_LABELS = {
    'watchlist': '真实历史快照 · 小样本观察池',
    'mainDemo': '主系统：演示数据',
    'mainCache': '主系统：缓存数据',
    'mainUnknown': '主系统数据模式未知',
    'history': '历史快照，非实时行情',
    'notAccepted': '完整选股、候选池与交易能力尚未验收',
}
DEFAULT_TECHNICAL = {
    'close': {'label': '收盘价', 'unit': 'price'},
    'mom120': {'label': '120日动量', 'unit': 'percent'},
    'mom20': {'label': '20日动量', 'unit': 'percent'},
    'vol60': {'label': '60日年化波动率', 'unit': 'percent'},
    'high252': {'label': '252日最高价', 'unit': 'price'},
    'low252': {'label': '252日最低价', 'unit': 'price'},
    'near_high_250': {'label': '距252日高点', 'unit': 'percent'},
    'drawdown_60d': {'label': '60日回撤', 'unit': 'percent'},
    'rsi14': {'label': 'RSI14', 'unit': 'index'},
    'vol_ratio': {'label': '量比（20日/60日）', 'unit': 'ratio'},
    'vol_contract': {'label': '波动收缩（20日/60日）', 'unit': 'ratio'},
    'ma50_up': {'label': 'MA50上行', 'unit': 'bool'},
    'ma200_up': {'label': 'MA200上行', 'unit': 'bool'},
}


class WatchlistError(Exception):
    """Locally defined safe error; the message is never copied from an exception."""

    def __init__(self, code, status, message):
        super().__init__(code)
        self.code = code
        self.status = status
        self.message = message


def _finite(value):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso_day(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if re.fullmatch(r'\d{8}', text):
        return f'{text[:4]}-{text[4:6]}-{text[6:]}'
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        return text
    return None


class RealWatchlistService:
    def __init__(self, root=None, config_path=None, sample_path=None, data_settings=None):
        self.root = Path(root or ROOT).resolve()
        self.config_path = Path(config_path) if config_path else self.root / 'config/real_watchlist.json'
        self.sample_override = Path(sample_path) if sample_path else None
        self.data_settings = data_settings
        self.config = self._load_config()

    # ---------- configuration ----------
    def _load_config(self):
        config = {'title': '真实观察池', 'eyebrow': 'WORKSPACE / REAL WATCHLIST',
                  'sampleConfig': 'config/real_data_sample.json', 'displayLimit': 1000,
                  'financeLimit': 200, 'labels': dict(DEFAULT_LABELS),
                  'technical': {key: dict(value) for key, value in DEFAULT_TECHNICAL.items()}}
        try:
            value = json.loads(self.config_path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeError):
            return config
        if not isinstance(value, dict):
            return config
        for key in ('title', 'eyebrow', 'sampleConfig'):
            if isinstance(value.get(key), str) and value[key].strip():
                config[key] = value[key]
        for key in ('displayLimit', 'financeLimit'):
            number = value.get(key)
            if isinstance(number, int) and not isinstance(number, bool) and number > 0:
                config[key] = number
        config['displayLimit'] = min(int(config['displayLimit']), 1000)
        config['financeLimit'] = min(int(config['financeLimit']), 500)
        labels = value.get('labels')
        if isinstance(labels, dict):
            for key in DEFAULT_LABELS:
                if isinstance(labels.get(key), str) and labels[key].strip():
                    config['labels'][key] = labels[key]
        technical = value.get('technical')
        if isinstance(technical, dict):
            for key in TECHNICAL:
                item = technical.get(key)
                if isinstance(item, dict) and isinstance(item.get('label'), str):
                    unit = item.get('unit') if item.get('unit') in ('percent', 'price', 'index', 'ratio', 'bool') else DEFAULT_TECHNICAL[key]['unit']
                    config['technical'][key] = {'label': item['label'], 'unit': unit}
        return config

    def _sample_config(self):
        path = self.sample_override or (self.root / self.config['sampleConfig'])
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeError):
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照配置不可读。') from None
        symbols = value.get('symbols') if isinstance(value, dict) else None
        if not isinstance(symbols, list) or not 0 < len(symbols) <= 10:
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照名单缺失或超限。')
        roster = []
        seen = set()
        for item in symbols:
            code = item.get('code') if isinstance(item, dict) else None
            name = item.get('name') if isinstance(item, dict) else None
            if not isinstance(code, str) or not CODE_RE.fullmatch(code) or code in seen:
                raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照名单格式非法。')
            seen.add(code)
            roster.append({'code': code, 'name': name if isinstance(name, str) and name else code})
        output = value.get('output_dir')
        if not isinstance(output, str) or not output.strip():
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照目录未配置。')
        return {'symbols': roster, 'output_dir': output}

    def _safe_file(self, out, name):
        try:
            from data.real_data_sample import private_path
            return private_path(self.root, out / name)
        except WatchlistError:
            raise
        except Exception:
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照路径不安全或不可用。') from None

    def _out_dir(self, sample):
        raw = Path(sample['output_dir'])
        target = raw if raw.is_absolute() else self.root / raw
        return self._safe_file(target.parent, target.name)

    # ---------- read helpers ----------
    @staticmethod
    def _read_json(path):
        try:
            if path.stat().st_size > 4 * 1024 * 1024:
                return None
            value = json.loads(path.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, UnicodeError):
            return None

    @staticmethod
    def _file_time(path):
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace('+00:00', 'Z')
        except OSError:
            return None

    def _connect(self, db):
        if not db.is_file():
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照数据库不存在。')
        try:
            connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=2.0)
        except sqlite3.Error:
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照数据库无法只读打开。') from None
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA busy_timeout = 1500')
        except sqlite3.Error:
            pass
        return connection

    def _open_snapshot(self):
        sample = self._sample_config()
        out = self._out_dir(sample)
        db = self._safe_file(out, 'bars.db')
        if not db.is_file():
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照尚未生成。')
        # 先取版本快照，再读取报告，避免「旧报告 + 新行情」混在一次响应里
        revision = self._revision(sample, out)
        if revision is None:
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照版本不可计算。')
        verification = self._read_json(self._safe_file(out, 'verification.json')) or {}
        readiness = self._read_json(self._safe_file(out, 'strategy_readiness.json')) or {}
        if self._revision(sample, out) != revision:
            raise WatchlistError('SNAPSHOT_CHANGED', 409, '快照正在更新，请稍后刷新。')
        return sample, out, db, verification, readiness, revision

    def _revision(self, sample, out):
        digest = hashlib.sha256()
        digest.update(json.dumps({'codes': [item['code'] for item in sample['symbols']],
                                  'output': sample['output_dir']}, sort_keys=True).encode('utf-8'))
        names = ['bars.db', 'verification.json', 'strategy_readiness.json']
        names += [item['code'] + '_' + suffix for item in sample['symbols']
                  for suffix in ('stock_basic.csv', 'finance_asof.csv', 'suspend_d.csv')]
        try:
            for name in names:
                path = self._safe_file(out, name)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                digest.update(f'{name}|{stat.st_size}|{stat.st_mtime_ns}'.encode('utf-8'))
        except WatchlistError:
            return None
        return digest.hexdigest()[:16]

    @staticmethod
    def _require_table(connection):
        row = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_bar'").fetchone()
        if row is None:
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照数据库结构不可用。')

    def _stock_basic(self, out, code):
        path = self._safe_file(out, code + '_stock_basic.csv')
        if not path.is_file():
            return {}
        try:
            with path.open('r', encoding='utf-8-sig', newline='') as handle:
                for row in csv.DictReader(handle):
                    if row.get('ts_code') != code:
                        continue
                    name = (row.get('name') or '').strip()
                    industry = (row.get('industry') or '').strip()
                    return {'name': name or None, 'industry': industry or None,
                            'listDate': _iso_day(row.get('list_date'))}
        except (OSError, UnicodeError, csv.Error):
            return {}
        return {}

    def _finance(self, out, code):
        path = self._safe_file(out, code + '_finance_asof.csv')
        if not path.is_file():
            return [], 0
        rows = []
        try:
            with path.open('r', encoding='utf-8-sig', newline='') as handle:
                for row in csv.DictReader(handle):
                    item = {}
                    for key in FINANCE_COLUMNS:
                        if key in ('end_date', 'ann_date'):
                            item[key] = _iso_day(row.get(key))
                        else:
                            item[key] = _finite(row.get(key))
                    rows.append(item)
        except (OSError, UnicodeError, csv.Error):
            return [], 0
        # 报告期倒序，rowCount 报总行数，截断只影响展示条数
        rows.sort(key=lambda item: item.get('end_date') or '', reverse=True)
        return rows[:self.config['financeLimit']], len(rows)

    @staticmethod
    def _verification(verification, code):
        symbols = verification.get('symbols')
        item = symbols.get(code) if isinstance(symbols, dict) else None
        if not isinstance(item, dict):
            return {'status': 'unavailable', 'passed': False, 'repeatWriteReadback': None,
                    'suspensionEvidenceDays': 0, 'missingDateCount': 0,
                    'note': '该股票缺少采集校验记录。'}
        passed = item.get('status') == 'passed'
        explicit = item.get('explicit_suspensions') if isinstance(item.get('explicit_suspensions'), dict) else {}
        evidence = item.get('suspension_evidence') if isinstance(item.get('suspension_evidence'), dict) else {}
        missing = item.get('missing_dates') if isinstance(item.get('missing_dates'), list) else []
        return {'status': 'passed' if passed else 'failed', 'passed': passed,
                'repeatWriteReadback': item.get('repeat_write_readback') if isinstance(item.get('repeat_write_readback'), bool) else None,
                'suspensionEvidenceDays': len(set(explicit) | set(evidence)),
                'missingDateCount': len(missing),
                'note': '采集校验通过。' if passed else '该股票采集校验未通过，数据仅供排查。'}

    def _main_mode(self):
        labels = self.config['labels']
        mode = {'mode': 'unknown', 'label': labels['mainUnknown'],
                'note': '无法读取主系统数据配置，不能判定当前数据来源，也不默认为真实数据。'}
        try:
            settings = self.data_settings
            if settings is None:
                try:
                    from .data_settings import DataSettings
                except ImportError:
                    from data_settings import DataSettings
                settings = DataSettings(self.root / 'config/params.yaml',
                                        metadata_path=self.root / 'config/data_sources.json')
            config, _ = settings._load()
            data = config.get('data') if isinstance(config, dict) else None
            if not isinstance(data, dict):
                raise ValueError('data section missing')
            value = settings._data_mode(data)
            kind = value.get('kind') if value.get('kind') in ('demo', 'cache') else 'unknown'
            label = labels['mainDemo'] if kind == 'demo' else (labels['mainCache'] if kind == 'cache' else labels['mainUnknown'])
            note = value.get('note') if isinstance(value.get('note'), str) else mode['note']
            return {'mode': kind, 'label': label, 'note': note}
        except Exception:
            return mode

    def _rows(self, out, db, sample, verification):
        connection = self._connect(db)
        stocks = []
        finance_total = 0
        latest = None
        try:
            self._require_table(connection)
            codes = [item['code'] for item in sample['symbols']]
            placeholders = ','.join('?' for _ in codes)
            total = connection.execute(
                f'SELECT COUNT(*) FROM daily_bar WHERE code IN ({placeholders})', codes).fetchone()[0]
            for item in sample['symbols']:
                code = item['code']
                basic = self._stock_basic(out, code)
                finance_rows, finance_count = self._finance(out, code)
                finance_total += finance_count
                check = self._verification(verification, code)
                row = {'code': code, 'name': basic.get('name') or item['name'],
                       'industry': basic.get('industry'), 'close_unadjusted': None,
                       'pct_chg': None, 'latest_date': None, 'history_count': 0,
                       'verification_status': check['status'], 'status': 'failed', 'note': ''}
                try:
                    latest_bar = connection.execute(
                        'SELECT date, close, pct_chg FROM daily_bar WHERE code=? AND adjust=? '
                        'ORDER BY date DESC LIMIT 1', (code, 'none')).fetchone()
                    count = connection.execute(
                        'SELECT COUNT(*) FROM daily_bar WHERE code=? AND adjust=?',
                        (code, 'none')).fetchone()[0]
                except sqlite3.Error:
                    row['note'] = '快照行情读取失败。'
                    stocks.append(row)
                    continue
                if latest_bar is None or not count:
                    row['note'] = '快照中没有该股票的未复权行情。'
                else:
                    row.update(close_unadjusted=_finite(latest_bar['close']),
                               pct_chg=_finite(latest_bar['pct_chg']),
                               latest_date=_iso_day(str(latest_bar['date'])),
                               history_count=int(count))
                    if check['status'] == 'passed':
                        row['status'] = 'ok'
                    else:
                        row['note'] = check['note']
                if row['latest_date'] and (latest is None or row['latest_date'] > latest):
                    latest = row['latest_date']
                stocks.append(row)
        except sqlite3.Error:
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照数据库读取失败。') from None
        finally:
            connection.close()
        return stocks, {'symbols': len(sample['symbols']), 'bars': int(total),
                        'financeRows': finance_total, 'latestDate': latest}

    def _as_of(self, verification, scope):
        value = _iso_day(verification.get('as_of')) if isinstance(verification.get('as_of'), str) else None
        return value or (scope or {}).get('latestDate')

    def _source(self, verification, scope, main):
        labels = self.config['labels']
        as_of = self._as_of(verification, scope)
        return {'kind': 'real_sample', 'label': labels['watchlist'], 'asOf': as_of,
                'mainMode': main['mode'],
                'note': f'{labels["history"]}；{main["label"]}；{labels["notAccepted"]}。'}

    # ---------- public API ----------
    def context(self):
        main = self._main_mode()
        labels = self.config['labels']
        try:
            sample, out, db, verification, readiness, revision = self._open_snapshot()
            stocks, scope = self._rows(out, db, sample, verification)
            if self._revision(sample, out) != revision:
                raise WatchlistError('SNAPSHOT_CHANGED', 409, '快照正在更新，请稍后刷新。')
            symbols = verification.get('symbols') if isinstance(verification.get('symbols'), dict) else {}
            passed = verification.get('passed') is True and all(
                isinstance(symbols.get(item['code']), dict) and symbols[item['code']].get('status') == 'passed'
                for item in sample['symbols'])
            status = 'passed' if passed else ('failed' if verification else 'unavailable')
            verification_path = self._safe_file(out, 'verification.json')
            watchlist = {
                'mode': 'real_sample',
                'label': '此页：' + labels['watchlist'],
                'asOf': self._as_of(verification, scope),
                'scope': scope,
                'collectedAt': self._file_time(verification_path),
                'verification': {'status': status, 'passed': passed,
                                 'demoUnchanged': verification.get('demo_unchanged') is True},
                'revision': revision,
                'strategyAcceptance': False,
                'notes': [labels['history'], main['label'], labels['notAccepted']],
            }
        except WatchlistError:
            watchlist = {'mode': 'unavailable', 'label': '此页：真实历史快照不可用', 'asOf': None,
                         'scope': None, 'collectedAt': None,
                         'verification': {'status': 'unavailable', 'passed': False,
                                          'demoUnchanged': False},
                         'revision': None, 'strategyAcceptance': False,
                         'notes': [labels['history'], main['label'], labels['notAccepted']]}
        return {'ok': True, 'page': {'title': self.config['title'], 'eyebrow': self.config['eyebrow']},
                'main': main, 'watchlist': watchlist}

    def list_stocks(self):
        sample, out, db, verification, readiness, revision = self._open_snapshot()
        main = self._main_mode()
        stocks, scope = self._rows(out, db, sample, verification)
        if self._revision(sample, out) != revision:
            raise WatchlistError('SNAPSHOT_CHANGED', 409, '快照正在更新，请稍后刷新。')
        return {'ok': True, 'revision': revision, 'source': self._source(verification, scope, main),
                'scope': scope, 'stocks': stocks}

    def stock_detail(self, code, adjust, expected_revision=None):
        sample = self._sample_config()
        roster = {item['code'] for item in sample['symbols']}
        if not isinstance(code, str) or not CODE_RE.fullmatch(code) or code not in roster:
            raise WatchlistError('NOT_FOUND', 404, '该股票不在真实观察池名单中。')
        if adjust not in ADJUST_LABELS:
            raise WatchlistError('INVALID_ADJUST', 400, '仅支持未复权或前复权。')
        sample, out, db, verification, readiness, revision = self._open_snapshot()
        if expected_revision and expected_revision != revision:
            raise WatchlistError('SNAPSHOT_CHANGED', 409, '快照已更新，请重新加载。')
        main = self._main_mode()

        connection = self._connect(db)
        try:
            self._require_table(connection)
            total = connection.execute(
                'SELECT COUNT(*) FROM daily_bar WHERE code=? AND adjust=?',
                (code, adjust)).fetchone()[0]
            rows = connection.execute(
                f"SELECT {','.join(BAR_COLUMNS)} FROM daily_bar WHERE code=? AND adjust=? "
                'ORDER BY date DESC LIMIT ?', (code, adjust, self.config['displayLimit'])).fetchall()
        except sqlite3.Error:
            raise WatchlistError('SAMPLE_UNAVAILABLE', 503, '真实快照行情读取失败。') from None
        finally:
            connection.close()

        bars = []
        if rows:
            frame = normalize_units(pd.DataFrame([dict(row) for row in rows], columns=list(BAR_COLUMNS)))
            for record in reversed(frame.to_dict('records')):
                bars.append({'date': _iso_day(str(record.get('date'))),
                             'open': _finite(record.get('open')), 'high': _finite(record.get('high')),
                             'low': _finite(record.get('low')), 'close': _finite(record.get('close')),
                             'preclose': _finite(record.get('preclose')),
                             'volume': _finite(record.get('volume')),
                             'amount': _finite(record.get('amount')), 'turn': _finite(record.get('turn')),
                             'pct_chg': _finite(record.get('pct_chg'))})

        check = self._verification(verification, code)
        basic = self._stock_basic(out, code)
        finance_rows, finance_count = self._finance(out, code)
        symbols = readiness.get('symbols') if isinstance(readiness.get('symbols'), dict) else {}
        technical_item = symbols.get(code) if isinstance(symbols.get(code), dict) else {}
        raw_factors = technical_item.get('technical_factors') if isinstance(technical_item.get('technical_factors'), dict) else {}
        factors = {key: _finite(raw_factors.get(key)) for key in TECHNICAL}
        available = bool(raw_factors)
        blockers = readiness.get('blockers') if isinstance(readiness.get('blockers'), list) else []
        blockers = [value for value in blockers if value in STRATEGY_BLOCKERS]
        history_count = len(bars) if not (rows and total) else total

        if self._revision(sample, out) != revision:
            raise WatchlistError('SNAPSHOT_CHANGED', 409, '快照正在更新，请稍后刷新。')

        scope = {'symbols': len(sample['symbols']), 'bars': None, 'financeRows': None,
                 'latestDate': bars[-1]['date'] if bars else None}
        return {
            'ok': True, 'revision': revision, 'source': self._source(verification, scope, main),
            'stock': {'code': code, 'name': basic.get('name') or next(
                item['name'] for item in sample['symbols'] if item['code'] == code),
                'industry': basic.get('industry'), 'listDate': basic.get('listDate'),
                'latestDate': bars[-1]['date'] if bars else None,
                'historyCount': history_count, 'verificationStatus': check['status'],
                'status': 'ok' if bars and check['passed'] else 'failed',
                'note': check['note']},
            'adjust': {'value': adjust, 'label': ADJUST_LABELS[adjust]},
            'bars': bars, 'barsTotal': int(total), 'barsReturned': len(bars),
            'barsTruncated': int(total) > len(bars),
            'units': {'price': '元', 'volume': '股', 'amount': '元'},
            'finance': {'available': bool(finance_rows), 'rows': finance_rows, 'rowCount': finance_count,
                        'note': '供应商原始财务指标；年/累计口径，不是单季指标，未经验证。'},
            'technical': {'available': available, 'status': technical_item.get('status') if isinstance(technical_item.get('status'), str) else 'unavailable',
                          'factors': factors, 'fields': self.config['technical'],
                          'blockers': blockers, 'strategyAcceptance': False,
                          'note': '仅复用已生成的样本技术指标；完整策略、评分、胜率与排名尚未验收。'},
            'verification': dict(check, demoUnchanged=verification.get('demo_unchanged') is True),
        }
