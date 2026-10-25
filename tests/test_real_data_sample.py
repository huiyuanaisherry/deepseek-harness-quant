import json
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from data.real_data_sample import ValidationError, prepare_bars, validate_finance, write_verified, run
from data.cache import DailyCache, normalize_units


class RealSampleTests(unittest.TestCase):
    def setUp(self):
        self.daily = pd.DataFrame(dict(ts_code=['000001.SZ']*2, trade_date=['20260102','20260105'], open=[10.,12.], high=[11.,13.], low=[9.,11.], close=[10.,12.], pre_close=[9.,10.], vol=[2.,3.], amount=[4.,5.], pct_chg=[1.,2.]))
        self.factor = pd.DataFrame(dict(ts_code=['000001.SZ']*2, trade_date=['20260102','20260105'], adj_factor=[1.,2.]))
        self.basic = pd.DataFrame(dict(ts_code=['000001.SZ']*2, trade_date=['20260102','20260105'], turnover_rate=[1.,2.]))

    def bars(self):
        return prepare_bars(self.daily, self.factor, self.basic, ['20260102','20260105'])

    def test_adjustment_and_units_and_repeat_read(self):
        raw, qfq = self.bars()
        self.assertEqual(qfq.close.tolist(), [5.,12.])
        self.assertEqual(qfq.preclose.tolist(), [4.5,10.])
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp)/'untouched.db'
            other.write_bytes(b'unchanged')
            cache = DailyCache(Path(tmp)/'bars.db')
            self.assertTrue(write_verified(cache, '000001.SZ', raw, qfq))
            self.assertTrue(write_verified(cache, '000001.SZ', raw, qfq))
            got = cache.get_daily('000001.SZ', adjust='none')
            self.assertEqual(len(got), 2)
            self.assertEqual(normalize_units(got).volume.tolist(), [200.,300.])
            self.assertEqual(normalize_units(got).amount.tolist(), [4000.,5000.])
            self.assertEqual(other.read_bytes(), b'unchanged')

    def test_shifted_snapshot_rejected_before_either_adjustment_mutates(self):
        raw, qfq = self.bars()
        for existing_adjustments in [('none','qfq'), ('qfq',)]:
            with self.subTest(existing=existing_adjustments), tempfile.TemporaryDirectory() as tmp:
                cache = DailyCache(Path(tmp)/'bars.db')
                for adjust, frame in [('none',raw),('qfq',qfq)]:
                    if adjust in existing_adjustments:
                        cache.put_daily('000001.SZ',frame,adjust=adjust,source='tushare')
                before = {a:cache.get_daily('000001.SZ',adjust=a) for a in ['none','qfq']}
                shifted_raw = raw.copy()
                shifted_qfq = qfq.copy()
                shifted_raw['date'] = ['2026-01-05','2026-01-06']
                shifted_qfq['date'] = shifted_raw.date
                with self.assertRaisesRegex(ValidationError,'cache_window_conflict_use_new_output'):
                    write_verified(cache,'000001.SZ',shifted_raw,shifted_qfq)
                for adjust, original in before.items():
                    after = cache.get_daily('000001.SZ',adjust=adjust)
                    if original is None:
                        self.assertIsNone(after)
                    else:
                        pd.testing.assert_frame_equal(after, original)

    def test_bad_inputs_rejected(self):
        for kind in ['duplicate','negative','factor','calendar','alignment']:
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'duplicate': self.daily = pd.concat([self.daily,self.daily.iloc[:1]])
                if kind == 'negative': self.daily.loc[0,'close'] = -1
                if kind == 'factor': self.factor.loc[0,'adj_factor'] = 0
                if kind == 'calendar': self.daily = self.daily.iloc[:1]
                if kind == 'alignment': self.factor = self.factor.iloc[:1]
                with self.assertRaises(ValidationError): self.bars()

    def test_runner_bounded_collection_and_private_evidence(self):
        frames = {'daily':self.daily, 'adj_factor':self.factor, 'daily_basic':self.basic.assign(pe=1.,pb=1.,total_mv=1.,circ_mv=1.),
                  'stock_basic':pd.DataFrame([dict(ts_code='000001.SZ',symbol='000001',name='sample',industry='sample',list_date='19910101',list_status='L')]),
                  'fina_indicator':pd.DataFrame([dict(ts_code='000001.SZ',ann_date='20251020',end_date='20250930',roe=1.,eps=1.,netprofit_yoy=1.,or_yoy=1.,grossprofit_margin=1.,debt_to_assets=1.,ocfps=1.,revenue_ps=1.)]),
                  'trade_cal':pd.DataFrame(dict(exchange=['SSE']*4,cal_date=['20260102','20260103','20260104','20260105'],is_open=[1,0,0,1]))}
        calls = []
        class Client:
            def __getattr__(self, api):
                def query(**kwargs):
                    calls.append((api,kwargs))
                    return frames[api].copy()
                return query
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'data/demo').mkdir(parents=True)
            (root/'data/demo/bars.db').write_bytes(b'demo')
            config = root/'config.json'
            config.write_text(json.dumps(dict(symbols=[dict(code='000001.SZ',name='sample')],history_days=3,finance_days=730)))
            report,path = run(config,'2026-01-05',Client(),root)
            self.assertTrue(report['passed'],report)
            self.assertTrue(report['demo_unchanged'])
            self.assertEqual(report['latest_expected_trading_date'],'20260105')
            self.assertEqual(len(calls),6)
            self.assertTrue(all('limit' in kwargs for _,kwargs in calls))
            self.assertTrue(path.is_file())
            self.assertTrue((path.parent/'000001.SZ_daily.csv').is_file())
            report,_ = run(config,'2026-01-05',Client(),root)
            self.assertTrue(report['passed'])
            frames['daily'].loc[0,'close'] = -1
            report,_ = run(config,'2026-01-05',Client(),root)
            self.assertFalse(report['passed'])
            self.assertEqual(report['symbols']['000001.SZ']['error'],'invalid_numeric')
            self.assertTrue((path.parent/'000001.SZ_daily.csv').is_file())

    def test_network_only_retry(self):
        from deck.model_settings import SettingsError
        for failure, expected_calls in [('NETWORK', 2), ('PERMISSION', 1)]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                calls = []
                class Client:
                    def trade_cal(self, **kwargs):
                        calls.append(kwargs)
                        if len(calls) == 1:
                            raise SettingsError(failure, 502)
                        return pd.DataFrame(dict(exchange=['SSE']*4,cal_date=['20260102','20260103','20260104','20260105'],is_open=[1,0,0,1]))
                    def __getattr__(self, api):
                        def query(**kwargs):
                            code = kwargs['ts_code']
                            if api == 'stock_basic':
                                return pd.DataFrame([dict(ts_code=code,symbol='000001',name='sample',industry='sample',list_date='19910101',list_status='L')])
                            if api == 'daily': return daily.copy()
                            if api == 'adj_factor': return factors.copy()
                            if api == 'daily_basic': return basic.assign(pe=1.,pb=1.,total_mv=1.,circ_mv=1.)
                            return pd.DataFrame([dict(ts_code=code,ann_date='20251020',end_date='20250930',roe=1.,eps=1.,netprofit_yoy=1.,or_yoy=1.,grossprofit_margin=1.,debt_to_assets=1.,ocfps=1.,revenue_ps=1.)])
                        return query
                daily, factors, basic = self.daily, self.factor, self.basic
                root = Path(tmp)
                config = root/'config.json'
                config.write_text(json.dumps(dict(symbols=[dict(code='000001.SZ',name='sample')],history_days=3)))
                report,_ = run(config,'2026-01-05',Client(),root)
                self.assertEqual(len(calls),expected_calls)
                self.assertEqual(report['passed'], failure == 'NETWORK',report)
                self.assertEqual(report['query_attempts']['trade_cal'],expected_calls)
                if failure == 'PERMISSION': self.assertEqual(report['error'],'PERMISSION')

    def test_supplier_full_day_suspension_required(self):
        for kind, timing, expected in [('S',None,True),('R',None,False),('S','09:30-10:30',False)]:
            with self.subTest(kind=kind,timing=timing), tempfile.TemporaryDirectory() as tmp:
                frames = {
                    'daily':self.daily.iloc[1:].copy(),
                    'adj_factor':self.factor,
                    'daily_basic':self.basic.assign(pe=1.,pb=1.,total_mv=1.,circ_mv=1.),
                    'stock_basic':pd.DataFrame([dict(ts_code='000001.SZ',symbol='000001',name='sample',industry='sample',list_date='19910101',list_status='L')]),
                    'fina_indicator':pd.DataFrame([dict(ts_code='000001.SZ',ann_date='20251020',end_date='20250930',roe=1.,eps=1.,netprofit_yoy=1.,or_yoy=1.,grossprofit_margin=1.,debt_to_assets=1.,ocfps=1.,revenue_ps=1.)]),
                    'trade_cal':pd.DataFrame(dict(exchange=['SSE']*4,cal_date=['20260102','20260103','20260104','20260105'],is_open=[1,0,0,1])),
                    'suspend_d':pd.DataFrame([dict(ts_code='000001.SZ',trade_date='20260102',suspend_timing=timing,suspend_type=kind)])}
                calls = []
                class Client:
                    def __getattr__(self, api):
                        def query(**kwargs):
                            calls.append((api,kwargs))
                            return frames[api].copy()
                        return query
                root = Path(tmp)
                config = root/'config.json'
                config.write_text(json.dumps(dict(symbols=[dict(code='000001.SZ',name='sample')],history_days=3)))
                report,path = run(config,'2026-01-05',Client(),root)
                self.assertEqual(report['passed'],expected,report)
                raw_path = path.parent/'000001.SZ_suspend_d.csv'
                self.assertTrue(raw_path.is_file())
                self.assertEqual(pd.read_csv(raw_path).suspend_type.iloc[0],kind)
                request = [kwargs for api,kwargs in calls if api == 'suspend_d']
                self.assertEqual(len(request),1)
                self.assertEqual(request[0]['start_date'],'20260102')
                self.assertEqual(request[0]['end_date'],'20260102')
                if expected:
                    self.assertEqual(report['symbols']['000001.SZ']['suspension_evidence']['20260102'],raw_path.name)
                    self.assertEqual(report['symbols']['000001.SZ']['rows'],1)
                else:
                    self.assertEqual(report['symbols']['000001.SZ']['error'],'unverified_missing_dates')

    def test_invalid_pct_change_rejected(self):
        self.daily['pct_chg'] = ['broken', 2.]
        with self.assertRaises(ValidationError):
            self.bars()

    def test_signed_pct_change_and_turnover_validation(self):
        self.daily.loc[0, 'pct_chg'] = -3.
        raw, _ = self.bars()
        self.assertEqual(raw.pct_chg.iloc[0], -3.)
        self.basic['turnover_rate'] = self.basic.turnover_rate.astype(object)
        for invalid in [-1., float('nan'), float('inf'), 'broken']:
            self.basic.loc[0, 'turnover_rate'] = invalid
            with self.assertRaises(ValidationError):
                self.bars()

    def test_readback_checks_turn_and_pct_change(self):
        raw, qfq = self.bars()
        for column in ['turn', 'pct_chg']:
            with self.subTest(column=column), tempfile.TemporaryDirectory() as tmp:
                class CorruptReadback(DailyCache):
                    def get_daily(self, *args, **kwargs):
                        frame = super().get_daily(*args, **kwargs)
                        if frame is not None:
                            frame.loc[0, column] = 999.
                        return frame
                with self.assertRaises(ValidationError):
                    write_verified(CorruptReadback(Path(tmp)/'bars.db'), '000001.SZ', raw, qfq)

    def test_private_output_symlink_rejected_before_write(self):
        for target in ['anchor', 'database', 'report', 'csv']:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                demo = root/'data/demo'
                demo.mkdir(parents=True)
                protected = demo/'protected'
                protected.write_bytes(b'unchanged')
                anchor = root/'data/real-smoke'
                out = anchor/'sample'
                if target == 'anchor':
                    anchor.symlink_to(demo, target_is_directory=True)
                else:
                    out.mkdir(parents=True)
                    name = {'database':'bars.db','report':'verification.json','csv':'trade_cal.csv'}[target]
                    (out/name).symlink_to(protected)
                config = root/'config.json'
                config.write_text(json.dumps(dict(symbols=[dict(code='000001.SZ',name='sample')])))
                with self.assertRaises(ValidationError):
                    run(config,'2026-01-05',object(),root)
                self.assertEqual(protected.read_bytes(), b'unchanged')
                self.assertFalse((demo/'sample').exists())

    def test_nullable_finance_revision_tie_preserves_values(self):
        frame = pd.DataFrame(dict(ts_code=['000001.SZ']*3,
                                  end_date=['20250930']*3,
                                  ann_date=['20251020']*3,
                                  roe=[None, 2., 2.],
                                  eps=[None, None, None]))
        selected = validate_finance(frame, '20260105')
        reversed_selected = validate_finance(frame.iloc[::-1], '20260105')
        pd.testing.assert_frame_equal(selected, reversed_selected)
        self.assertTrue(pd.isna(selected.roe.iloc[0]))
        self.assertTrue(pd.isna(selected.eps.iloc[0]))
        self.assertTrue(frame.eps.isna().all())

    def test_finance_point_in_time_and_deterministic_revision(self):
        f = pd.DataFrame(dict(ts_code=['000001.SZ']*2, end_date=['20250930']*2, ann_date=['20251020','20251025'], roe=[1.,2.]))
        self.assertEqual(validate_finance(f,'20260105').roe.tolist(), [2.])
        f.loc[0,'ann_date'] = '20270101'
        with self.assertRaises(ValidationError): validate_finance(f,'20260105')

if __name__ == '__main__': unittest.main()
