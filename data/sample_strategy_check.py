"""Offline readiness diagnostic for the existing strategy; never a recommendation."""
import argparse
import json
import os
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TECHNICAL = ('close', 'mom120', 'mom20', 'vol60', 'high252', 'low252',
             'near_high_250', 'drawdown_60d', 'rsi14', 'vol_ratio',
             'vol_contract', 'ma50_up', 'ma200_up')
BLOCKERS = ['historical_ST_status_unknown', 'quarterly_financial_conversion_missing',
            'full_market_valuation_quantiles_missing', 'external_factor_coverage_unknown']


def technical_factors(code, bars, name, industry):
    """Reuse original indicators with isolated missing financial/quality/valuation inputs."""
    from factors.opportunities.scan import compute_factors
    px = bars.set_index('date')[['close']].rename(columns={'close': code})
    vx = bars.set_index('date')[['volume']].rename(columns={'volume': code})
    fin = pd.DataFrame(columns=['roe', 'sq_net_yoy', 'sq_rev_yoy', 'gross_margin'])
    basic = pd.DataFrame({'name': [name], 'industry': [industry]}, index=[code])
    result = compute_factors(px, vx, fin, basic, {code},
                             quality_loader=lambda: pd.DataFrame(), valuation_loader=lambda: {})
    # Explicit whitelist excludes legacy price-rank fallback and unknown ST/financial flags.
    row = result.loc[code]
    return {key: float(row[key]) if pd.notna(row[key]) and np.isfinite(row[key]) else None
            for key in TECHNICAL}


def run(config_path, root=ROOT):
    root = Path(root).resolve()
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    # Avoid cache's module-level production config fallback while importing shared path guards.
    previous = os.environ.get('LWQUANT_CACHE_DIR')
    os.environ['LWQUANT_CACHE_DIR'] = str(root / 'data/real-smoke/sample')
    try:
        from data.real_data_sample import private_path, require
        from data.cache import DailyCache
    finally:
        if previous is None:
            os.environ.pop('LWQUANT_CACHE_DIR', None)
        else:
            os.environ['LWQUANT_CACHE_DIR'] = previous
    out = private_path(root, root / config.get('output_dir', 'data/real-smoke/sample'))
    def local(name):
        return private_path(root, out / name)
    target = local('strategy_readiness.json')
    db = local('bars.db')
    verification_path = local('verification.json')
    symbols = config.get('symbols', [])
    require(0 < len(symbols) <= 10, 'symbol_limit')
    require(all(re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', s['code']) for s in symbols), 'invalid_symbol')
    require(len({s['code'] for s in symbols}) == len(symbols), 'duplicate_symbol')
    verification = json.loads(verification_path.read_text()) if verification_path.is_file() else {}
    passed = verification.get('passed') is True and all(
        verification.get('symbols', {}).get(s['code'], {}).get('status') == 'passed' for s in symbols)

    class ReadOnlyCache(DailyCache):
        def __init__(self, path):
            self.db_path = path
            self.inc_path = None
        def _conn(self):
            return sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True)

    report = {'input_verification_passed': passed, 'input_scope': 'complete' if passed else 'incomplete',
              'strategy_status': 'blocked', 'strategy_acceptance': False,
              'blockers': BLOCKERS, 'scope_note': 'Six-stock technical sample is not the market; no full-market ranks or strategy performance validated.',
              'financial_semantics': 'Provider annual/cumulative growth is not single-quarter growth; financial factors remain unknown.',
              'trigger_status': 'not_evaluated_pending_historical_ST_evidence', 'symbols': {}}
    cache = ReadOnlyCache(db) if db.is_file() else None
    for sample in symbols:
        code = sample['code']
        item = {'status': 'blocked', 'strategy_acceptance': False, 'history_count': 0,
                'latest_date': None, 'financial_coverage_rows': 0}
        report['symbols'][code] = item
        if verification.get('symbols', {}).get(code, {}).get('status') != 'passed':
            item['reason'] = 'symbol_input_verification_not_passed'
            continue
        if cache is None:
            item['reason'] = 'private_database_missing'
            continue
        bars = cache.get_daily(code, adjust='qfq')
        if bars is None or bars.empty:
            item['reason'] = 'private_bars_missing_or_unreadable'
            continue
        bars = bars.sort_values('date')
        item.update(history_count=len(bars), latest_date=str(bars.date.iloc[-1]))
        if len(bars) < 320:
            item['reason'] = 'insufficient_history'
            continue
        prices = pd.to_numeric(bars.close, errors='coerce')
        volume = pd.to_numeric(bars.volume, errors='coerce')
        if bars.date.duplicated().any() or not np.isfinite(prices).all() or not (prices > 0).all() or not np.isfinite(volume).all() or not (volume >= 0).all():
            item['reason'] = 'invalid_technical_inputs'
            continue
        basic_path = local(code + '_stock_basic.csv')
        if not basic_path.is_file():
            item['reason'] = 'stock_basic_missing'
            continue
        basic = pd.read_csv(basic_path, dtype=str)
        if len(basic) != 1 or not {'ts_code', 'name', 'industry'}.issubset(basic.columns) or basic.ts_code.iloc[0] != code:
            item['reason'] = 'stock_basic_invalid'
            continue
        finance_path = local(code + '_finance_asof.csv')
        if finance_path.is_file():
            try:
                item['financial_coverage_rows'] = len(pd.read_csv(finance_path))
            except (pd.errors.EmptyDataError, pd.errors.ParserError):
                item['financial_coverage_status'] = 'unreadable'
        item['technical_factors'] = technical_factors(code, bars, basic.name.iloc[0], basic.industry.iloc[0])
        item['status'] = 'technical_ready' if all(v is not None for v in item['technical_factors'].values()) else 'technical_incomplete'
        item['financial_factors_status'] = 'unknown'
    out.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return report, target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(ROOT / 'config/real_data_sample.json'))
    args = parser.parse_args()
    try:
        report, path = run(args.config)
        print('report: ' + str(path))
        return 0 if report['input_verification_passed'] and all(s['status'] == 'technical_ready' for s in report['symbols'].values()) else 1
    except Exception:
        print('strategy_readiness_failed: invalid_or_unreadable_private_inputs')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
