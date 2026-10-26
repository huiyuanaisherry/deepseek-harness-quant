"""Release regressions; synthetic local inputs only."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd
from deck import portal_status as ps, live_api
from factors.policy import global_rotation as gr


class PortalReleaseTest(unittest.TestCase):
    def test_pool_date_is_business_date(self):
        self.assertEqual(ps.extract_data_date({'pool_date': '2000-01-01'}), '2000-01-01')

    def test_undated_result_cannot_be_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'result.json'
            p.write_text('{"items": []}')
            result = ps.assess_artifact(p, item_keys=('items',), stale_days=4)
            self.assertEqual(result['status']['state'], 'blocked')

    def test_failed_payload_cannot_be_valid_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'result.json'
            p.write_text(json.dumps({'ok': False, 'date': '2026-10-26', 'items': []}))
            result = ps.assess_artifact(p, item_keys=('items',), stale_days=4)
            self.assertEqual(result['status']['state'], 'error')

    def test_actual_rotation_producer_schema_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            output.mkdir()
            (output / 'global_rotation.json').write_text(json.dumps({
                'date': date.today().isoformat(), 'a_share_weak': False,
                'global_rotation': None, 'weak_vote': 0, 'params': {}}))
            modules = live_api._portal_modules('demo', {}, tmp)
            self.assertEqual(modules['global_rotation']['state'], 'ready')

    def test_absent_sources_do_not_produce_completed_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            modules = live_api._portal_modules('demo', {'brief': {'ok': True, 'items': []}}, tmp)
            self.assertEqual(modules['brief']['state'], 'blocked')


class RotationReleaseTest(unittest.TestCase):
    def test_unverified_mapping_blocked(self):
        items = [{'key': 'x', 'column': None, 'column_index': 0, 'support': 'unverified'}]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'input.parquet').touch()
            with mock.patch.object(gr, '_read_parquet', return_value=pd.DataFrame({'x': [1, 2]}, index=pd.date_range('2026-10-22', periods=2))):
                with self.assertRaises(gr.RotationInputError) as ctx:
                    gr._load_panel(tmp, 'input.parquet', items, 2)
                self.assertEqual(ctx.exception.reason, 'asset_unverified')

    def test_stale_asset_not_hidden_by_panel_latest_row(self):
        frame = pd.DataFrame({'a': [1., None], 'b': [1., 2.]}, index=pd.to_datetime(['2026-09-01', '2026-10-23']))
        with self.assertRaises(gr.RotationInputError):
            gr._check_lag([frame], date(2026, 10, 26))

    def test_mixed_panel_dates_rejected(self):
        a = pd.DataFrame({'a': [1.]}, index=pd.to_datetime(['2026-10-22']))
        b = pd.DataFrame({'b': [1.]}, index=pd.to_datetime(['2026-10-23']))
        with self.assertRaises(gr.RotationInputError):
            gr._check_lag([a, b], date(2026, 10, 26))

    def test_future_data_rejected(self):
        frame = pd.DataFrame({'a': [1.]}, index=pd.to_datetime(['2026-10-27']))
        with self.assertRaises(gr.RotationInputError):
            gr._check_lag([frame], date(2026, 10, 26))

class ReadonlyDateTest(unittest.TestCase):
    def test_absent_database_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'absent'
            self.assertIsNone(ps.readonly_data_date(root))
            self.assertFalse(root.exists())

    def test_existing_database_is_not_modified(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / 'bars.db'
            con = sqlite3.connect(p)
            con.execute('CREATE TABLE daily_bar (code TEXT, date TEXT)')
            con.execute("INSERT INTO daily_bar VALUES ('000938.SZ', '2026-10-23')")
            con.commit()
            con.close()
            before = p.read_bytes()
            self.assertEqual(ps.readonly_data_date(root), '2026-10-23')
            self.assertEqual(p.read_bytes(), before)
            self.assertEqual([x.name for x in root.iterdir()], ['bars.db'])

    def test_active_wal_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bars.db').touch()
            (root / 'bars.db-wal').write_bytes(b'pending')
            self.assertIsNone(ps.readonly_data_date(root))


class HomepageReadonlyTest(unittest.TestCase):
    def test_batch_review_does_not_persist_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'cache.json'
            entry = {'code': '000001.SZ', 'entry_date': '2026-10-22',
                     'fwd': {'t1': {'date': '2026-10-23', 'ret': .01}}}
            with mock.patch.object(live_api, '_MKT_CACHE_FILE', p), mock.patch.object(live_api, '_mkt_median_cache', {}):
                live_api._batch_review_payload([entry])
            self.assertFalse(p.exists())

    def test_homepage_does_not_auto_fetch_or_probe_mutating_endpoints(self):
        html = (Path(__file__).resolve().parents[1] / 'ui_v2/pages/portal.html').read_text()
        self.assertNotIn('  loadRealtime();', html)
        self.assertNotIn('  loadApiStatus();', html)
        self.assertNotIn('setInterval(loadRealtime', html)
        self.assertNotIn('setInterval(loadApiStatus', html)
        self.assertIn("if (st !== 'ready') { hBad.push(k); }", html)
