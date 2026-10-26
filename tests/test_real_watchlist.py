"""Read-only real watchlist tests built entirely from synthetic private snapshots."""
import csv
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from data.cache import DailyCache
from deck import deck_server
from deck.real_watchlist import RealWatchlistService, WatchlistError
from deck.web_security import Security

SYMBOLS = [('000001.SZ', '测试甲', '电子'), ('000002.SZ', '测试乙', '计算机')]
DATES = ['2026-10-22', '2026-10-23']
TECHNICAL = ('close', 'mom120', 'mom20', 'vol60', 'high252', 'low252',
             'near_high_250', 'drawdown_60d', 'rsi14', 'vol_ratio',
             'vol_contract', 'ma50_up', 'ma200_up')
FINANCE_FIELDS = {'end_date', 'ann_date', 'eps', 'roe', 'netprofit_yoy', 'or_yoy',
                  'grossprofit_margin', 'debt_to_assets', 'ocfps', 'revenue_ps'}
BAR_FIELDS = {'date', 'open', 'high', 'low', 'close', 'preclose', 'volume',
              'amount', 'turn', 'pct_chg'}


def write_csv(path, header, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ('config', 'data/demo', 'data/real-smoke/sample', 'ui_v2/pages'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.sample = self.root / 'data/real-smoke/sample'
        (self.root / 'config/params.yaml').write_text('data:\n  cache_dir: data/demo\n', encoding='utf-8')
        sample = {'symbols': [{'code': code, 'name': name, 'suspended_dates': {}}
                              for code, name, _ in SYMBOLS],
                  'output_dir': 'data/real-smoke/sample', 'max_rows': 1000}
        (self.root / 'config/real_data_sample.json').write_text(json.dumps(sample, ensure_ascii=False), encoding='utf-8')
        self.make_snapshot()
        self.env = patch.dict(os.environ, {'LWQUANT_CACHE_DIR': str(self.root / 'data/demo')})
        self.env.start()
        self.service = RealWatchlistService(root=self.root)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def make_snapshot(self, verification_failed=()):
        cache = DailyCache(db_path=self.sample / 'bars.db')
        for index, (code, name, industry) in enumerate(SYMBOLS):
            base = 10.0 + index
            for adjust, factor in (('none', 1.0), ('qfq', 0.95)):
                frame = pd.DataFrame({
                    'date': DATES,
                    'open': [base * factor, (base + 1) * factor],
                    'high': [base * factor + 0.5, (base + 1) * factor + 0.5],
                    'low': [base * factor - 0.5, (base + 1) * factor - 0.5],
                    'close': [base * factor, (base + 1) * factor],
                    'preclose': [base * factor, base * factor],
                    'volume': [100, 120],
                    'amount': [1000, 1320],
                    'turn': [1.0, 1.2],
                    'pct_chg': [1.0, 2.0],
                    'is_st': [0, 0],
                })
                cache.put_daily(code, frame, adjust=adjust, source='tushare')
            write_csv(self.sample / (code + '_stock_basic.csv'),
                      ['ts_code', 'symbol', 'name', 'industry', 'list_date', 'list_status'],
                      [[code, code[:6], name, industry, '20100101', 'L']])
            write_csv(self.sample / (code + '_finance_asof.csv'),
                      ['ts_code', 'ann_date', 'end_date', 'roe', 'eps', 'netprofit_yoy',
                       'or_yoy', 'grossprofit_margin', 'debt_to_assets', 'ocfps', 'revenue_ps'],
                      [[code, '20260830', '20260630', '12.5', '0.35', '', '8.0', '', '45.0', '', '']])
        report = {'as_of': '20261023', 'passed': not verification_failed, 'demo_unchanged': True,
                  'units': {'volume': 'hand (100 shares)', 'amount': 'thousand CNY'}, 'symbols': {}}
        readiness = {'strategy_acceptance': False,
                     'blockers': ['historical_ST_status_unknown'], 'symbols': {}}
        for code, _, _ in SYMBOLS:
            report['symbols'][code] = {
                'status': 'failed' if code in verification_failed else 'passed',
                'rows': 2, 'latest_date': '2026-10-23', 'finance_rows': 1,
                'missing_dates': [], 'explicit_suspensions': {}, 'suspension_evidence': {},
                'suspension_verification_mode': 'none', 'repeat_write_readback': True,
                'expected_count': 2, 'observed_count': 2}
            readiness['symbols'][code] = {
                'status': 'technical_ready', 'history_count': 2, 'latest_date': '2026-10-23',
                'technical_factors': {key: 1.5 for key in TECHNICAL}}
        (self.sample / 'verification.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        (self.sample / 'strategy_readiness.json').write_text(json.dumps(readiness, ensure_ascii=False), encoding='utf-8')

    def digest(self):
        result = {}
        for path in sorted(self.sample.rglob('*')):
            if path.is_file():
                result[str(path.relative_to(self.sample))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result


class ServiceTests(Fixture):
    def test_actual_asof_is_not_query_cutoff(self):
        path = self.sample / 'verification.json'
        report = json.loads(path.read_text())
        report['as_of'] = '20261025'
        path.write_text(json.dumps(report))
        for value in (self.service.list_stocks(), self.service.stock_detail('000001.SZ', 'none')):
            self.assertEqual(value['source']['asOf'], '2026-10-23')
            self.assertEqual(value['source']['queryCutoff'], '2026-10-25')
        self.assertEqual(self.service.context()['watchlist']['asOf'], '2026-10-23')

    def test_stale_verification_rejects_changed_coverage(self):
        for mutation in (
            "DELETE FROM daily_bar WHERE code='000001.SZ' AND date='2026-10-23'",
            "UPDATE daily_bar SET date='2026-10-24' WHERE code='000001.SZ' AND date='2026-10-23'",
            "INSERT INTO daily_bar SELECT code, '2026-10-24', open, high, low, close, preclose, volume, amount, turn, pct_chg, is_st, adjust, source FROM daily_bar WHERE code='000001.SZ' AND date='2026-10-23'",
        ):
            with self.subTest(mutation=mutation):
                (self.sample / 'bars.db').unlink()
                self.make_snapshot()
                with sqlite3.connect(self.sample / 'bars.db') as connection:
                    connection.execute(mutation)
                for read in (self.service.list_stocks, lambda: self.service.stock_detail('000001.SZ', 'qfq')):
                    with self.assertRaises(WatchlistError) as caught:
                        read()
                    self.assertEqual(caught.exception.code, 'SNAPSHOT_CHANGED')

    def test_readiness_coverage_must_match_before_serving_technical(self):
        path = self.sample / 'strategy_readiness.json'
        original = json.loads(path.read_text())
        for key, value in (('history_count', 1), ('latest_date', '2026-10-22')):
            report = json.loads(json.dumps(original))
            report['symbols']['000001.SZ'][key] = value
            path.write_text(json.dumps(report))
            with self.assertRaises(WatchlistError) as caught:
                self.service.stock_detail('000001.SZ', 'none')
            self.assertEqual(caught.exception.code, 'SNAPSHOT_CHANGED')
        original['symbols']['000001.SZ'].pop('history_count')
        path.write_text(json.dumps(original))
        self.assertFalse(self.service.stock_detail('000001.SZ', 'none')['technical']['available'])
        path.unlink()
        detail = self.service.stock_detail('000001.SZ', 'qfq')
        self.assertTrue(detail['verification']['passed'])
        self.assertFalse(detail['technical']['available'])

    def test_qfq_only_coverage_change_invalidates_list_and_detail(self):
        with sqlite3.connect(self.sample / 'bars.db') as connection:
            connection.execute("DELETE FROM daily_bar WHERE code='000001.SZ' AND adjust='qfq' AND date='2026-10-23'")
        for read in (self.service.list_stocks, lambda: self.service.stock_detail('000001.SZ', 'none')):
            with self.assertRaises(WatchlistError) as caught:
                read()
            self.assertEqual(caught.exception.code, 'SNAPSHOT_CHANGED')

    def test_sqlite_sidecar_symlinks_are_rejected_before_open(self):
        outside = self.root / 'outside-wal'
        outside.write_bytes(b'private synthetic sidecar')
        (self.sample / 'bars.db-wal').symlink_to(outside)
        with patch.object(self.service, '_connect', side_effect=AssertionError('unsafe open')):
            with self.assertRaises(WatchlistError) as caught:
                self.service.list_stocks()
        self.assertEqual(caught.exception.code, 'SAMPLE_UNAVAILABLE')

    def test_failed_verification_does_not_enable_technical(self):
        self.make_snapshot(verification_failed={'000001.SZ'})
        detail = self.service.stock_detail('000001.SZ', 'none')
        self.assertFalse(detail['verification']['passed'])
        self.assertFalse(detail['technical']['available'])

    def test_wal_changes_reject_old_revision_without_opening_database(self):
        writer = sqlite3.connect(self.sample / 'bars.db')
        try:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            sample, out, _, _, _, revision = self.service._open_snapshot()
            main_stat = (self.sample / 'bars.db').stat()
            writer.execute("UPDATE daily_bar SET close=99 WHERE code='000001.SZ'")
            writer.commit()
            current_stat = (self.sample / 'bars.db').stat()
            self.assertEqual((main_stat.st_size, main_stat.st_mtime_ns),
                             (current_stat.st_size, current_stat.st_mtime_ns))
            self.assertNotEqual(self.service._revision(sample, out), revision)
            before = self.digest()
            with patch.object(self.service, '_connect', side_effect=AssertionError('must reject before opening')):
                with self.assertRaises(WatchlistError) as caught:
                    self.service.stock_detail('000001.SZ', 'none', revision)
                self.assertEqual(caught.exception.code, 'SNAPSHOT_CHANGED')
                with self.assertRaises(WatchlistError) as caught:
                    self.service.list_stocks()
                self.assertEqual(caught.exception.code, 'SAMPLE_UNAVAILABLE')
            self.assertEqual(before, self.digest())
        finally:
            writer.close()

    def test_context_keeps_main_demo_and_watchlist_real_separate(self):
        value = self.service.context()
        self.assertTrue(value['ok'])
        self.assertEqual(value['main']['mode'], 'demo')
        self.assertEqual(value['main']['label'], '主系统：演示数据')
        self.assertEqual(value['watchlist']['mode'], 'real_sample')
        self.assertIn('真实历史快照', value['watchlist']['label'])
        self.assertEqual(value['watchlist']['asOf'], '2026-10-23')
        self.assertEqual(value['watchlist']['scope']['symbols'], 2)
        self.assertEqual(value['watchlist']['scope']['bars'], 8)
        self.assertEqual(value['watchlist']['scope']['financeRows'], 2)
        self.assertFalse(value['watchlist']['strategyAcceptance'])
        self.assertTrue(value['watchlist']['verification']['passed'])
        self.assertTrue(value['watchlist']['collectedAt'])
        for forbidden in ('token', 'endpoint', 'tushare_api_url'):
            self.assertNotIn(forbidden, json.dumps(value, ensure_ascii=False).lower())

    def test_unknown_main_mode_is_never_reported_as_real(self):
        (self.root / 'config/params.yaml').unlink()
        value = RealWatchlistService(root=self.root).context()
        self.assertEqual(value['main']['mode'], 'unknown')
        self.assertEqual(value['main']['label'], '主系统数据模式未知')

    def test_list_uses_dynamic_roster_and_marks_partial_failures(self):
        self.make_snapshot(verification_failed={'000002.SZ'})
        value = RealWatchlistService(root=self.root).list_stocks()
        self.assertTrue(value['ok'])
        self.assertEqual([row['code'] for row in value['stocks']], ['000001.SZ', '000002.SZ'])
        first, second = value['stocks']
        self.assertEqual(first['name'], '测试甲')
        self.assertEqual(first['industry'], '电子')
        self.assertEqual(first['close_unadjusted'], 11.0)
        self.assertEqual(first['pct_chg'], 2.0)
        self.assertEqual(first['latest_date'], '2026-10-23')
        self.assertEqual(first['history_count'], 2)
        self.assertEqual(first['status'], 'ok')
        self.assertEqual(second['status'], 'failed')
        self.assertIn('历史快照', value['source']['note'])
        self.assertEqual(value['source']['asOf'], '2026-10-23')

    def test_detail_units_converted_once_and_sorted_ascending(self):
        value = self.service.stock_detail('000001.SZ', 'qfq')
        self.assertEqual(value['revision'], self.service.list_stocks()['revision'])
        self.assertEqual([bar['date'] for bar in value['bars']], DATES)
        self.assertEqual(value['bars'][0]['close'], 9.5)
        self.assertEqual(value['bars'][1]['volume'], 12000)
        self.assertEqual(value['bars'][1]['amount'], 1320000)
        self.assertEqual(value['units'], {'price': '元', 'volume': '股', 'amount': '元'})
        self.assertEqual(set(value['bars'][0]), BAR_FIELDS)
        self.assertEqual(set(value['finance']['rows'][0]), FINANCE_FIELDS)
        self.assertIsNone(value['finance']['rows'][0]['netprofit_yoy'])
        self.assertEqual(value['finance']['rows'][0]['roe'], 12.5)
        self.assertEqual(value['finance']['rows'][0]['end_date'], '2026-06-30')
        self.assertEqual(set(value['technical']['factors']), set(TECHNICAL))
        self.assertFalse(value['technical']['strategyAcceptance'])

    def test_filtered_adjust_and_limits(self):
        config = self.root / 'config/tight.json'
        config.write_text(json.dumps({'sampleConfig': 'config/real_data_sample.json', 'displayLimit': 1}), encoding='utf-8')
        service = RealWatchlistService(root=self.root, config_path=config)
        value = service.stock_detail('000001.SZ', 'none')
        self.assertEqual(len(value['bars']), 1)
        self.assertTrue(value['barsTruncated'])
        self.assertEqual(value['bars'][0]['date'], '2026-10-23')

    def test_invalid_inputs(self):
        for code in ('999999.SZ', '000001.SZ\n', '../000001.SZ'):
            with self.assertRaises(WatchlistError) as caught:
                self.service.stock_detail(code, 'none')
            self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(WatchlistError) as caught:
            self.service.stock_detail('000001.SZ', 'hfq')
        self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(WatchlistError) as caught:
            self.service.stock_detail('000001.SZ', 'none', 'deadbeef')
        self.assertEqual(caught.exception.status, 409)

    def test_missing_snapshot_is_unavailable_and_symlinks_rejected(self):
        (self.sample / 'bars.db').unlink()
        service = RealWatchlistService(root=self.root)
        self.assertEqual(service.context()['watchlist']['mode'], 'unavailable')
        with self.assertRaises(WatchlistError) as caught:
            service.list_stocks()
        self.assertEqual(caught.exception.status, 503)

        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'bars.db').write_bytes(b'')
        replacement = self.root / 'data/real-smoke/link'
        replacement.symlink_to(outside)
        sample = self.root / 'config/real_data_sample.json'
        data = json.loads(sample.read_text(encoding='utf-8'))
        data['output_dir'] = 'data/real-smoke/link'
        sample.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        with self.assertRaises(WatchlistError) as caught:
            RealWatchlistService(root=self.root).list_stocks()
        self.assertEqual(caught.exception.status, 503)

    def test_reads_use_parameterized_readonly_sql_without_dailycache(self):
        calls = []
        statements = []
        real_connect = sqlite3.connect

        def spy(database, *args, **kwargs):
            calls.append(str(database))
            connection = real_connect(database, *args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection

        with patch('deck.real_watchlist.sqlite3.connect', side_effect=spy), \
                patch.object(DailyCache, '__init__', side_effect=AssertionError('DailyCache write')):
            self.service.list_stocks()
            self.service.stock_detail('000001.SZ', 'none')
        self.assertTrue(calls)
        self.assertEqual(statements.count('BEGIN'), len(calls))
        for uri in calls:
            self.assertIn('mode=ro', uri)
            self.assertNotIn('immutable', uri)

    def test_non_finite_values_become_null_and_reads_do_not_mutate(self):
        connection = sqlite3.connect(self.sample / 'bars.db')
        connection.execute("UPDATE daily_bar SET pct_chg=? WHERE code='000001.SZ' AND adjust='none' AND date='2026-10-23'",
                           (float('inf'),))
        connection.commit()
        connection.close()
        before = self.digest()
        service = RealWatchlistService(root=self.root)
        listing = service.list_stocks()
        detail = service.stock_detail('000001.SZ', 'none')
        self.assertIsNone(listing['stocks'][0]['pct_chg'])
        self.assertIsNone(detail['bars'][-1]['pct_chg'])
        self.assertEqual(before, self.digest())

    def test_snapshot_changing_mid_read_is_reported_as_conflict(self):
        service = self.service
        original = service._revision
        calls = {'count': 0}

        def flaky(sample, out):
            calls['count'] += 1
            return original(sample, out) if calls['count'] == 1 else 'changed-%d' % calls['count']

        with patch.object(service, '_revision', side_effect=flaky):
            with self.assertRaises(WatchlistError) as caught:
                service.list_stocks()
            self.assertEqual(caught.exception.status, 409)
            calls['count'] = 0
            context = service.context()
        self.assertEqual(context['watchlist']['mode'], 'unavailable')
        self.assertFalse(context['watchlist']['strategyAcceptance'])
        self.assertEqual(context['main']['mode'], 'demo')

    def test_output_directory_outside_private_root_is_rejected(self):
        sample = self.root / 'config/real_data_sample.json'
        data = json.loads(sample.read_text(encoding='utf-8'))
        data['output_dir'] = 'data/demo'
        sample.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        with self.assertRaises(WatchlistError) as caught:
            RealWatchlistService(root=self.root).list_stocks()
        self.assertEqual(caught.exception.status, 503)

    def test_zero_close_stays_numeric_and_missing_finance_is_unavailable(self):
        connection = sqlite3.connect(self.sample / 'bars.db')
        connection.execute("UPDATE daily_bar SET close=0 WHERE code='000001.SZ' AND adjust='none' AND date='2026-10-23'")
        connection.commit()
        connection.close()
        (self.sample / '000002.SZ_finance_asof.csv').unlink()
        first = self.service.stock_detail('000001.SZ', 'none')
        self.assertEqual(first['bars'][-1]['close'], 0.0)
        second = self.service.stock_detail('000002.SZ', 'none')
        self.assertFalse(second['finance']['available'])
        self.assertEqual(second['finance']['rows'], [])
        self.assertEqual(second['finance']['rowCount'], 0)

    def test_finance_rows_are_sorted_desc_and_report_total_count(self):
        config = self.root / 'config/tight-finance.json'
        config.write_text(json.dumps({'sampleConfig': 'config/real_data_sample.json', 'financeLimit': 1}),
                          encoding='utf-8')
        write_csv(self.sample / '000001.SZ_finance_asof.csv',
                  ['ts_code', 'ann_date', 'end_date', 'roe', 'eps', 'netprofit_yoy',
                   'or_yoy', 'grossprofit_margin', 'debt_to_assets', 'ocfps', 'revenue_ps'],
                  [['000001.SZ', '20260430', '20260331', '9.0', '0.2', '', '', '', '', '', ''],
                   ['000001.SZ', '20260830', '20260630', '12.5', '0.35', '', '', '', '', '', '']])
        service = RealWatchlistService(root=self.root, config_path=config)
        value = service.stock_detail('000001.SZ', 'none')
        self.assertEqual(len(value['finance']['rows']), 1)
        self.assertEqual(value['finance']['rowCount'], 2)
        self.assertEqual(value['finance']['rows'][0]['end_date'], '2026-06-30')


class HandlerTests(Fixture):
    def setUp(self):
        super().setUp()
        (self.root / 'ui_v2/pages/real-watchlist.html').write_text('REAL WATCHLIST PAGE', encoding='utf-8')
        (self.root / 'ui_v2/pages/settings.html').write_text('SETTINGS PAGE', encoding='utf-8')
        (self.root / 'ui_v2/pages/data-settings.html').write_text('DATA SETTINGS PAGE', encoding='utf-8')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), deck_server.Handler)
        self.server.security = Security(self.root / 'auth/token')
        self.server.real_watchlist = RealWatchlistService(root=self.root)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_port
        self.cookie = ''
        self.started = patch.object(deck_server, 'BASE', self.root)
        self.started.start()

    def tearDown(self):
        self.started.stop()
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def request(self, path):
        connection = HTTPConnection('127.0.0.1', self.port)
        connection.request('GET', path, headers={'Cookie': self.cookie})
        response = connection.getresponse()
        body = response.read()
        header = response.getheader('Cache-Control')
        connection.close()
        return response.status, body, header

    def login(self):
        status, _, _ = self.request('/login')
        self.assertEqual(status, 200)
        token = self.server.security.token
        connection = HTTPConnection('127.0.0.1', self.port)
        connection.request('POST', '/api/auth/login', json.dumps({'token': token}),
                           {'Content-Type': 'application/json', 'X-Quant-Request': '1',
                            'Origin': f'http://127.0.0.1:{self.port}'})
        response = connection.getresponse()
        response.read()
        cookie = response.getheader('Set-Cookie')
        connection.close()
        self.assertEqual(response.status, 200)
        self.cookie = cookie.split(';')[0]

    def test_watchlist_routes_require_login(self):
        self.assertEqual(self.request('/api/data-context')[0], 401)
        self.assertEqual(self.request('/api/real-watchlist')[0], 401)
        self.assertEqual(self.request('/api/real-watchlist/stocks/000001.SZ')[0], 401)
        self.assertEqual(self.request('/real-watchlist')[0], 303)
        self.login()
        status, body, cache = self.request('/real-watchlist')
        self.assertEqual((status, body), (200, b'REAL WATCHLIST PAGE'))
        self.assertEqual(cache, 'no-store')
        self.assertEqual(self.request('/api/data-context')[0], 200)
        self.assertEqual(self.request('/api/data-context')[2], 'no-store')
        self.assertEqual(self.request('/api/real-watchlist')[0], 200)
        self.assertEqual(self.request('/api/real-watchlist')[2], 'no-store')
        status, body, _ = self.request('/api/real-watchlist/stocks/000001.SZ?adjust=qfq')
        self.assertEqual(status, 200)
        self.assertIn(b'9.5', body)
        self.assertEqual(self.request('/api/real-watchlist/stocks/999999.SZ')[0], 404)
        self.assertEqual(self.request('/api/real-watchlist/stocks/000001.SZ?adjust=hfq')[0], 400)
        self.assertEqual(self.request('/api/real-watchlist/stocks/000001.SZ?revision=deadbeef')[0], 409)

    def test_existing_routes_do_not_regress(self):
        class FakeSettings:
            def describe(self):
                return {'ok': True, 'revision': 'v1'}

        class FakeDataSettings:
            def describe(self):
                return {'ok': True, 'revision': 'v2', 'dataMode': {'kind': 'demo'}}

        self.server.model_settings = FakeSettings()
        self.server.data_settings = FakeDataSettings()
        self.login()
        self.assertEqual(self.request('/settings')[:2], (200, b'SETTINGS PAGE'))
        self.assertEqual(self.request('/data-settings')[:2], (200, b'DATA SETTINGS PAGE'))
        self.assertEqual(self.request('/api/model-settings')[0], 200)
        self.assertEqual(self.request('/api/data-settings/tushare')[0], 200)
        self.assertEqual(self.request('/api/navigation')[0], 200)
        self.assertEqual(self.request('/api/not-a-route')[0], 404)


if __name__ == '__main__':
    unittest.main()
