"""Bounded private Tushare sample collection; never changes production data paths."""
import argparse
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from data.cache import DailyCache
from deck.model_settings import SettingsError

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {
    'suspend_d': 'ts_code,trade_date,suspend_timing,suspend_type',
    'trade_cal': 'exchange,cal_date,is_open',
    'stock_basic': 'ts_code,symbol,name,industry,list_date,list_status',
    'daily': 'ts_code,trade_date,open,high,low,close,pre_close,vol,amount,pct_chg',
    'adj_factor': 'ts_code,trade_date,adj_factor',
    'daily_basic': 'ts_code,trade_date,turnover_rate,pe,pb,total_mv,circ_mv',
    'fina_indicator': 'ts_code,ann_date,end_date,roe,eps,netprofit_yoy,or_yoy,grossprofit_margin,debt_to_assets,ocfps,revenue_ps',
}


class ValidationError(ValueError):
    """Carries only a locally defined safe error code."""


def safe_error(exc, fallback):
    if isinstance(exc, ValidationError):
        return str(exc)
    code = getattr(exc, 'code', None)
    return code if code in {'NETWORK', 'CREDENTIALS', 'PERMISSION', 'RATE_LIMITED', 'UPSTREAM_ERROR', 'INVALID_ENDPOINT', 'INVALID_REQUEST', 'INSECURE_HTTP_CONFIRMATION_REQUIRED', 'CONFIG_READ_FAILED', 'TOKEN_REQUIRED', 'INVALID_TOKEN'} else fallback


def require(ok, code):
    if not ok:
        raise ValidationError(code)


def dates(series):
    text = series.astype(str)
    parsed = pd.to_datetime(text, format='%Y%m%d', errors='coerce')
    require(text.str.fullmatch(r'\d{8}').all() and parsed.notna().all(), 'invalid_date')
    return text


def prepare_bars(daily, factors, basic, expected):
    for frame, cols in [(daily, FIELDS['daily'].split(',')), (factors, ['trade_date','adj_factor']), (basic, ['trade_date','turnover_rate'])]:
        require(not frame.empty and set(cols).issubset(frame.columns), 'missing_fields')
        dates(frame.trade_date)
        require(not frame.trade_date.duplicated().any(), 'duplicate_date')
    observed = set(daily.trade_date)
    require(observed == set(expected), 'calendar_incomplete')
    require(observed == set(factors.trade_date) == set(basic.trade_date), 'date_alignment')
    joined = daily.merge(factors[['trade_date','adj_factor']], on='trade_date').merge(basic[['trade_date','turnover_rate']], on='trade_date').sort_values('trade_date').reset_index(drop=True)
    prices = ['open','high','low','close','pre_close']
    for col in prices + ['adj_factor','vol','amount','turnover_rate','pct_chg']:
        joined[col] = pd.to_numeric(joined[col], errors='coerce')
        require(np.isfinite(joined[col]).all(), 'invalid_numeric')
        require((joined[col] > 0).all() if col in prices + ['adj_factor'] else (True if col == 'pct_chg' else (joined[col] >= 0).all()), 'invalid_numeric')
    require((joined.high >= joined[prices].drop(columns='pre_close').max(axis=1)).all() and (joined.low <= joined[['open','close']].min(axis=1)).all(), 'invalid_ohlc')
    raw = joined.rename(columns={'trade_date':'date','pre_close':'preclose','vol':'volume','turnover_rate':'turn'}).copy()
    raw['date'] = pd.to_datetime(raw.date, format='%Y%m%d').dt.strftime('%Y-%m-%d')
    raw['is_st'] = 0  # unknown historical ST status; not an acceptance of ST-sensitive rules
    qfq = raw.copy()
    ratio = joined.adj_factor / joined.adj_factor.iloc[-1]
    for col in ['open','high','low','close','preclose']:
        qfq[col] = raw[col] * ratio
    return raw, qfq


def validate_finance(frame, as_of):
    require(not frame.empty and {'ts_code','ann_date','end_date'}.issubset(frame.columns), 'finance_missing')
    frame = frame.copy()
    for col in ['ann_date','end_date']:
        frame[col] = dates(frame[col])
        require((frame[col] <= as_of).all(), 'finance_future_date')
    require((frame.ann_date >= frame.end_date).all(), 'finance_invalid_disclosure')
    # Lexical row tie-break makes equal-disclosure revisions independent of response order.
    frame['_tie'] = frame.astype('string').fillna('').agg('|'.join, axis=1)
    return frame.sort_values(['end_date','ann_date','_tie']).drop_duplicates(['ts_code','end_date'], keep='last').drop(columns='_tie').reset_index(drop=True)


def write_verified(cache, code, raw, qfq):
    # This private cache holds a fixed snapshot. Use a new output directory when
    # changing the date window; check both adjustments before any mutation.
    for adjust, frame in [('none', raw), ('qfq', qfq)]:
        existing = cache.get_daily(code, adjust=adjust)
        require(existing is None or existing.empty or existing.date.tolist() == frame.date.tolist(),
                'cache_window_conflict_use_new_output')
    for adjust, frame in [('none',raw),('qfq',qfq)]:
        cache.put_daily(code, frame, adjust=adjust, source='tushare')
        first = cache.get_daily(code, adjust=adjust)
        require(first is not None and len(first) == len(frame), 'readback_count')
        for col in ['open','high','low','close','preclose','volume','amount','turn','pct_chg']:
            require(np.allclose(first[col], frame[col], equal_nan=True), 'readback_values')
        require(first.date.tolist() == frame.date.tolist(), 'readback_dates')
        cache.put_daily(code, frame, adjust=adjust, source='tushare')
        second = cache.get_daily(code, adjust=adjust)
        require(first.equals(second), 'repeat_write_mismatch')
    return True


def demo_signatures(root):
    signatures = {}
    for path in sorted((root/'data/demo').rglob('*')):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            signatures[str(path.relative_to(root))] = digest.hexdigest()
    return signatures


def private_path(root, path):
    """Reject existing symlink components before resolving private output paths."""
    root = Path(root).resolve()
    path = Path(path)
    require(path.is_absolute() and root in path.parents, 'unsafe_output_path')
    current = root
    for part in path.relative_to(root).parts:
        require(part not in {'.', '..'}, 'unsafe_output_path')
        current = current/part
        require(not current.is_symlink(), 'unsafe_output_path')
    resolved = path.resolve()
    anchor = root/'data/real-smoke'
    require(anchor in resolved.parents, 'unsafe_output_path')
    return resolved


def run(config_path, as_of=None, client=None, root=ROOT):
    root = Path(root).resolve()
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    symbols = config.get('symbols', [])
    require(0 < len(symbols) <= min(int(config.get('max_symbols',10)),10), 'symbol_limit')
    require(len({s['code'] for s in symbols}) == len(symbols), 'duplicate_symbol')
    require(all(re.fullmatch(r'\d{6}\.(SZ|SH|BJ)', s['code']) for s in symbols), 'invalid_symbol')
    history = int(config.get('history_days',730)); finance = int(config.get('finance_days',730))
    cap = int(config.get('max_rows',1000))
    network_attempts = int(config.get('network_attempts', 2))
    require(1 <= network_attempts <= 2, 'network_attempts_limit')
    require(1 <= history <= 730 and 1 <= finance <= 730 and 1 <= cap <= 1000, 'query_limit')
    stamp = date.fromisoformat(as_of) if as_of else date.today()
    end = stamp.strftime('%Y%m%d'); start = (stamp-timedelta(days=history)).strftime('%Y%m%d')
    out = private_path(root, root/config.get('output_dir','data/real-smoke/sample'))
    names = ['trade_cal.csv', 'bars.db', 'bars.db-journal', 'bars.db-wal', 'bars.db-shm', 'verification.json']
    names += [sample['code']+'_'+api+'.csv' for sample in symbols for api in ['stock_basic','daily','adj_factor','daily_basic','fina_indicator','finance_asof','suspend_d']]
    # Validate every possible destination before even creating output directories.
    for name in names:
        private_path(root, out/name)
    def destination(name):
        return private_path(root, out/name)
    out.mkdir(parents=True, exist_ok=True)
    before = demo_signatures(root)
    report = {'query_attempts':{},'as_of':end,'start_date':start,'symbols':{},'units':{'volume':'hand (100 shares)','amount':'thousand CNY','source':'tushare'},'finance_semantics':'raw provider indicators; growth not converted to single quarter','historical_st_status':'unknown; ST-sensitive strategy acceptance blocked','demo_before':before}
    if client is None:
        from data.fetcher_tushare import _pro
        client = _pro()
    def query(api, **params):
        limit = history+2 if api == 'trade_cal' else cap
        for attempt in range(network_attempts):
            report['query_attempts'][api] = report['query_attempts'].get(api, 0) + 1
            try:
                result = getattr(client, api)(fields=FIELDS[api], limit=limit, **params)
                break
            except SettingsError as exc:
                if exc.code != 'NETWORK' or attempt + 1 >= network_attempts:
                    raise
        require(isinstance(result,pd.DataFrame), 'invalid_response')
        limit = history+2 if api == 'trade_cal' else cap
        require(len(result) < limit, 'possible_truncation')
        require(set(FIELDS[api].split(',')).issubset(result.columns), 'missing_fields')
        return result
    try:
        calendar = query('trade_cal', exchange='SSE', start_date=start, end_date=end)
        calendar.to_csv(destination('trade_cal.csv'),index=False)
        dates(calendar.cal_date)
        require(not calendar.cal_date.duplicated().any(), 'duplicate_calendar')
        require(set(calendar.cal_date) == set(pd.date_range(start,end).strftime('%Y%m%d')), 'calendar_incomplete')
        require(calendar.is_open.astype(str).isin(['0','1']).all(), 'invalid_calendar')
        expected = sorted(calendar.loc[calendar.is_open.astype(str).eq('1'),'cal_date'])
        require(bool(expected), 'calendar_empty')
        report['latest_expected_trading_date'] = expected[-1]
        cache = DailyCache(db_path=destination('bars.db'))
        for sample in symbols:
            code = sample['code']; item = {'status':'failed'}; report['symbols'][code] = item
            try:
                frames = {}
                for api in ['stock_basic','daily','adj_factor','daily_basic','fina_indicator']:
                    params = {'ts_code':code}
                    if api != 'stock_basic': params.update(start_date=(stamp-timedelta(days=finance)).strftime('%Y%m%d') if api == 'fina_indicator' else start,end_date=end)
                    frame = query(api, **params)
                    frame.to_csv(destination(code+'_'+api+'.csv'),index=False)
                    require(not frame.empty and frame.ts_code.eq(code).all(), 'symbol_mismatch')
                    frames[api] = frame
                stock = frames['stock_basic']
                require(len(stock)==1 and stock.name.iloc[0] == sample['name'], 'stock_identity_mismatch')
                listing = dates(stock.list_date).iloc[0]
                wanted = [d for d in expected if d >= listing]
                allowed = sample.get('suspended_dates',{})
                require(isinstance(allowed,dict) and all(isinstance(v,str) and v.strip() for v in allowed.values()), 'invalid_suspension_evidence')
                missing = set(wanted)-set(frames['daily'].trade_date)
                item.update(expected_count=len(wanted),observed_count=len(frames['daily']),missing_dates=sorted(missing))
                verified = set(allowed)
                require(verified.issubset(missing), 'invalid_suspension_evidence')
                item['explicit_suspensions'] = allowed
                item['suspension_evidence'] = {}
                item['suspension_verification_mode'] = 'manual' if allowed else 'none'
                remaining = missing - verified
                if remaining:
                    evidence_name = code+'_suspend_d.csv'
                    suspension = query('suspend_d', ts_code=code, start_date=min(remaining), end_date=max(remaining))
                    suspension.to_csv(destination(evidence_name),index=False)
                    require(suspension.ts_code.eq(code).all(), 'suspension_symbol_mismatch')
                    suspension_dates = dates(suspension.trade_date)
                    require(suspension_dates.between(min(remaining),max(remaining)).all(), 'suspension_date_range')
                    require(suspension.suspend_type.isin(['S','R']).all(), 'suspension_invalid_type')
                    full_day = suspension.suspend_timing.isna() | suspension.suspend_timing.astype('string').fillna('').str.strip().eq('')
                    full_s = suspension.suspend_type.eq('S') & full_day
                    for missing_date in sorted(remaining):
                        records = suspension.trade_date.eq(missing_date)
                        if records.any() and full_s[records].all():
                            verified.add(missing_date)
                            item['suspension_evidence'][missing_date] = evidence_name
                    item['suspension_verification_mode'] = 'manual_and_supplier' if allowed else 'supplier'
                require(verified == missing, 'unverified_missing_dates')
                # Full-day suspensions can still have a published adjustment factor.
                # Permit only proven halted dates as extras, never arbitrary dates.
                observed = set(frames['daily'].trade_date)
                for api in ['adj_factor','daily_basic']:
                    frame = frames[api]
                    dates(frame.trade_date)
                    require(not frame.trade_date.duplicated().any(), 'duplicate_date')
                    require(set(frame.trade_date).issubset(observed | verified), 'date_alignment')
                    frames[api] = frame.loc[frame.trade_date.isin(observed)].copy()
                raw,qfq = prepare_bars(frames['daily'],frames['adj_factor'],frames['daily_basic'],[d for d in wanted if d not in verified])
                fin = validate_finance(frames['fina_indicator'],end)
                fin.to_csv(destination(code+'_finance_asof.csv'),index=False)
                item.update(rows=len(raw),finance_rows=len(fin),latest_date=raw.date.iloc[-1],repeat_write_readback=write_verified(cache,code,raw,qfq),status='passed')
            except Exception as exc:
                item['error'] = safe_error(exc, 'collection_or_storage_failed')
    except Exception as exc:
        report['error'] = safe_error(exc, 'calendar_or_storage_failed')
    report['demo_after'] = demo_signatures(root)
    report['demo_unchanged'] = before == report['demo_after']
    report['passed'] = report['demo_unchanged'] and not report.get('error') and len(report['symbols']) == len(symbols) and all(v['status']=='passed' for v in report['symbols'].values())
    destination('verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report, out/'verification.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default=str(ROOT/'config/real_data_sample.json'))
    parser.add_argument('--as-of', help='YYYY-MM-DD; run after daily publication')
    args = parser.parse_args()
    try:
        report,path = run(args.config,args.as_of)
        print('report: '+str(path))
        return 0 if report['passed'] else 1
    except Exception:
        print('sample_failed: invalid_configuration_or_client')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
