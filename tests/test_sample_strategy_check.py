import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from data.sample_strategy_check import run, technical_factors


class StrategyCheckTests(unittest.TestCase):
    def test_original_momentum_and_isolated_loaders(self):
        from factors.opportunities import scan
        bars = pd.DataFrame({'date': pd.bdate_range('2024-01-01', periods=330).strftime('%Y-%m-%d'),
                             'close': 20 + np.arange(330) * .02 + np.sin(np.arange(330)),
                             'volume': 100 + np.arange(330) % 9})
        with patch.object(scan, 'load_quality', side_effect=AssertionError('global quality')), patch.object(scan, 'load_valuation', side_effect=AssertionError('global valuation')):
            result = technical_factors('000938.SZ', bars, '紫光股份', '计算机')
        self.assertAlmostEqual(result['mom20'], bars.close.iloc[-1] / bars.close.iloc[-21] - 1)
        self.assertNotIn('pb_pct', result)
        self.assertNotIn('non_st', result)

    def fixture(self, root):
        out = root / 'data/real-smoke/sample'
        out.mkdir(parents=True)
        config = root / 'sample.json'
        config.write_text(json.dumps({'symbols': [{'code': '000938.SZ', 'name': '紫光股份'}], 'output_dir': 'data/real-smoke/sample'}))
        return out, config

    def test_missing_verification_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out, config = self.fixture(root)
            report, _ = run(config, root=root)
            self.assertFalse(report['input_verification_passed'])
            self.assertEqual(report['symbols']['000938.SZ']['status'], 'blocked')
            self.assertFalse((out / 'bars.db').exists())

    def test_short_history_and_demo_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out, config = self.fixture(root)
            from data.cache import DailyCache
            cache = DailyCache(out / 'bars.db')
            bars = pd.DataFrame({'date': pd.bdate_range('2024-01-01', periods=20).strftime('%Y-%m-%d'), 'close': np.arange(20) + 10., 'volume': 100.})
            cache.put_daily('000938.SZ', bars, source='tushare')
            (out / 'verification.json').write_text(json.dumps({'passed': True, 'symbols': {'000938.SZ': {'status': 'passed'}}}))
            demo = root / 'data/demo/test'; demo.parent.mkdir(); demo.write_text('original')
            report, _ = run(config, root=root)
            self.assertEqual(report['symbols']['000938.SZ']['reason'], 'insufficient_history')
            self.assertEqual(demo.read_text(), 'original')

    def test_verified_readonly_technical_run_with_partial_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out, config = self.fixture(root)
            from data.cache import DailyCache
            cache = DailyCache(out / 'bars.db')
            bars = pd.DataFrame({'date': pd.bdate_range('2024-01-01', periods=330).strftime('%Y-%m-%d'),
                                 'close': 20 + np.arange(330) * .02 + np.sin(np.arange(330)),
                                 'volume': 100 + np.arange(330) % 9})
            cache.put_daily('000938.SZ', bars, source='tushare')
            (out / '000938.SZ_stock_basic.csv').write_text('ts_code,name,industry\n000938.SZ,紫光股份,计算机\n')
            (out / 'verification.json').write_text(json.dumps({'passed': False, 'symbols': {'000938.SZ': {'status': 'passed'}}}))
            before = (out / 'bars.db').read_bytes()
            with patch.object(DailyCache, '_init_schema', side_effect=AssertionError('write schema')):
                report, _ = run(config, root=root)
            self.assertEqual(report['input_scope'], 'incomplete')
            self.assertEqual(report['symbols']['000938.SZ']['status'], 'technical_ready')
            self.assertFalse(report['strategy_acceptance'])
            self.assertEqual(before, (out / 'bars.db').read_bytes())

    def test_reject_symlink_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out, config = self.fixture(root)
            victim = root / 'victim'; victim.write_text('unchanged')
            (out / 'strategy_readiness.json').symlink_to(victim)
            with self.assertRaises(ValueError):
                run(config, root=root)
            self.assertEqual(victim.read_text(), 'unchanged')

    def test_reject_production_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); _, config = self.fixture(root)
            config.write_text(json.dumps({'symbols': [], 'output_dir': 'data/demo'}))
            with self.assertRaises(ValueError):
                run(config, root=root)
