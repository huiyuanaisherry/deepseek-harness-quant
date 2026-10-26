# -*- coding: utf-8 -*-
"""五福轮动输入就绪条件测试（Task 3）。

只使用临时合成数据，不访问真实供应商、不写仓库 output、不安装依赖。
需要 Parquet 引擎的用例在缺少引擎时跳过并说明原因。
"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factors.policy import global_rotation as gr  # noqa: E402

AS_OF = date(2026, 10, 26)
END = "2026-10-23"


def _config(*, etfs_by_index=False, support="unverified"):
    """合成映射配置：4 指数 + 9 ETF，列名可用显式名或位置。"""
    indices = [
        {"key": f"idx{i}", "name": f"指数{i}", "column": f"idx{i}",
         "column_index": i, "support": support}
        for i in range(4)
    ]
    if etfs_by_index:
        etfs = [
            {"key": f"etf{i}", "name": f"资产{i}", "column": None,
             "column_index": i, "support": support}
            for i in range(9)
        ]
    else:
        etfs = [
            {"key": f"etf{i}", "name": f"资产{i}", "column": f"etf{i}",
             "column_index": i, "support": support}
            for i in range(9)
        ]
    return {"schema_version": 1, "indices": indices, "etfs": etfs}


def _frames(n=80, *, weak=False, etf_cols=None, index_cols=None, end=END):
    idx = pd.bdate_range(end=end, periods=n)
    index_cols = index_cols or [f"idx{i}" for i in range(4)]
    etf_cols = etf_cols or [f"etf{i}" for i in range(9)]
    data = {}
    for i, col in enumerate(index_cols):
        base = 120.0 if not (weak and i < 3) else 140.0
        data[col] = np.linspace(base, base - 20.0 if (weak and i < 3) else base + 20.0, n)
    index_df = pd.DataFrame(data, index=idx)
    etf_data = {}
    for i, col in enumerate(etf_cols):
        etf_data[col] = np.linspace(100.0 + i, 100.0 + i + 35.0 + i, n)
    etf_df = pd.DataFrame(etf_data, index=idx)
    return index_df, etf_df


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.out = self.root / "out" / "global_rotation.json"
        self.out.parent.mkdir()
        self.cfg_path = self.root / "assets.json"

    def write_config(self, **kwargs):
        cfg = _config(**kwargs)
        self.cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return cfg

    def touch_inputs(self):
        (self.cache / "wufu_idx.parquet").write_bytes(b"PAR1")
        (self.cache / "wufu_etf.parquet").write_bytes(b"PAR1")

    def patch_frames(self, index_df, etf_df):
        frames = {"wufu_idx.parquet": index_df, "wufu_etf.parquet": etf_df}
        patcher = mock.patch.object(
            gr, "_read_parquet", side_effect=lambda p: frames[Path(p).name])
        patcher.start()
        self.addCleanup(patcher.stop)

    def expect_error(self, reason, state, func=None, **kwargs):
        func = func or gr.widget
        with self.assertRaises(gr.RotationInputError) as ctx:
            func(input_dir=self.cache, as_of=AS_OF,
                 config_path=self.cfg_path, **kwargs)
        self.assertEqual(ctx.exception.reason, reason)
        self.assertEqual(ctx.exception.state, state)
        return ctx.exception


class MissingInputsTest(_Base):
    def test_missing_file_is_blocked(self):
        self.write_config()
        self.expect_error("input_missing", "blocked")

    def test_missing_engine_is_blocked(self):
        self.write_config()
        self.touch_inputs()
        with mock.patch.object(gr, "_detect_engines", return_value=[]):
            self.expect_error("engine_unavailable", "blocked")

    def test_missing_column_is_blocked(self):
        self.write_config()
        self.touch_inputs()
        index_df, etf_df = _frames(index_cols=["idx0", "idx1", "idx2", "renamed"])
        self.patch_frames(index_df, etf_df)
        self.expect_error("column_missing", "blocked")

    def test_coverage_shortfall_is_blocked(self):
        self.write_config(etfs_by_index=True)
        self.touch_inputs()
        index_df, etf_df = _frames(etf_cols=[f"c{i}" for i in range(8)])
        self.patch_frames(index_df, etf_df)
        self.expect_error("coverage_insufficient", "blocked")

    def test_missing_config_is_blocked(self):
        self.touch_inputs()
        self.expect_error("config_missing", "blocked")

    def test_unsupported_asset_is_blocked(self):
        cfg = self.write_config()
        cfg["etfs"][2]["support"] = "unsupported"
        self.cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        self.touch_inputs()
        index_df, etf_df = _frames()
        self.patch_frames(index_df, etf_df)
        err = self.expect_error("asset_unsupported", "blocked")
        self.assertIn("etf2", err.detail)


class StaleAndInvalidTest(_Base):
    def setUp(self):
        super().setUp()
        self.write_config()
        self.touch_inputs()

    def test_lagging_dates_are_blocked(self):
        index_df, etf_df = _frames(end="2026-09-01")
        self.patch_frames(index_df, etf_df)
        self.expect_error("input_stale", "blocked", func=gr.compute, out_path=self.out)
        self.assertFalse(self.out.exists())

    def test_index_history_too_short_is_blocked(self):
        index_df, etf_df = _frames(n=10)
        self.patch_frames(index_df, etf_df)
        self.expect_error("history_insufficient", "blocked")

    def test_etf_history_too_short_is_blocked(self):
        index_df = _frames()[0]
        etf_df = _frames(n=60)[1]
        self.patch_frames(index_df, etf_df)
        self.expect_error("history_insufficient", "blocked")

    def test_non_positive_price_is_error(self):
        index_df, etf_df = _frames()
        index_df.iloc[-1, 0] = 0.0
        self.patch_frames(index_df, etf_df)
        self.expect_error("price_non_positive", "error")

    def test_infinite_price_is_error(self):
        index_df, etf_df = _frames()
        etf_df.iloc[-1, 3] = np.inf
        self.patch_frames(index_df, etf_df)
        self.expect_error("price_non_positive", "error")

    def test_nan_latest_index_row_is_error(self):
        index_df, etf_df = _frames()
        index_df.iloc[-1, 0] = np.nan
        self.patch_frames(index_df, etf_df)
        self.expect_error("input_invalid", "error", func=gr.compute, out_path=self.out)
        self.assertFalse(self.out.exists())


class ComputableSampleTest(_Base):
    def setUp(self):
        super().setUp()
        self.write_config()
        self.touch_inputs()

    def test_widget_returns_finite_numbers(self):
        index_df, etf_df = _frames(weak=True)
        self.patch_frames(index_df, etf_df)
        w = gr.widget(input_dir=self.cache, as_of=AS_OF, config_path=self.cfg_path)
        self.assertEqual(w["date"], END)
        self.assertEqual(len(w["assets"]), 9)
        self.assertEqual(sorted(a["name"] for a in w["assets"]),
                         sorted(f"资产{i}" for i in range(9)))
        moms = [a["mom_ann"] for a in w["assets"]]
        self.assertEqual(moms, sorted(moms, key=lambda v: -(v if v is not None else -9)),
                         "摆件保持既有按动量降序展示")
        nums = []
        for a in w["assets"]:
            nums.extend([a["ret20"], a["ret60"], a["mom_ann"], a["r2"]])
            self.assertIsInstance(a["above_ma10"], bool)
        for v in nums:
            if v is None:
                continue
            self.assertTrue(np.isfinite(v), f"non-finite value: {v}")

    def test_compute_matches_weak_vote_and_writes_strict_json(self):
        index_df, etf_df = _frames(weak=True)
        self.patch_frames(index_df, etf_df)
        out = gr.compute(input_dir=self.cache, out_path=self.out,
                         as_of=AS_OF, config_path=self.cfg_path)
        self.assertTrue(out["a_share_weak"])
        self.assertEqual(out["weak_vote"], 3)
        self.assertIsNotNone(out["global_rotation"])
        text = self.out.read_text(encoding="utf-8")
        self.assertNotIn("NaN", text)
        self.assertNotIn("Infinity", text)
        json.loads(text, parse_constant=lambda c: self.fail(f"非有限数值 {c}"))

    def test_reads_synthetic_parquet_with_real_engine(self):
        if not gr._detect_engines():
            self.skipTest("本机无 pyarrow/fastparquet，跳过真实 Parquet 读取")
        index_df, etf_df = _frames(weak=True)
        index_df.to_parquet(self.cache / "wufu_idx.parquet")
        etf_df.to_parquet(self.cache / "wufu_etf.parquet")
        w = gr.widget(input_dir=self.cache, as_of=AS_OF, config_path=self.cfg_path)
        self.assertEqual(w["date"], END)
        self.assertEqual(len(w["assets"]), 9)


class RepositoryConfigTest(unittest.TestCase):
    def test_config_declares_four_indices_and_nine_etfs(self):
        path = ROOT / "config" / "global_rotation_assets.json"
        self.assertTrue(path.exists(), "缺少 config/global_rotation_assets.json")
        cfg = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(cfg["indices"]), 4)
        self.assertEqual(len(cfg["etfs"]), 9)
        keys = set()
        for group in ("indices", "etfs"):
            for item in cfg[group]:
                for field in ("key", "name", "column", "column_index",
                              "vendor", "vendor_symbol", "support",
                              "permission", "alternative", "note"):
                    self.assertIn(field, item, f"{group} 缺字段 {field}")
                self.assertIn(item["support"], ("verified", "unverified", "unsupported"))
                self.assertNotIn("/Users/", json.dumps(item))
                keys.add((group, item["key"]))
        self.assertEqual(len(keys), 13)

    def test_example_matches_config_schema(self):
        real = ROOT / "config" / "global_rotation_assets.json"
        example = ROOT / "config" / "global_rotation_assets.json.example"
        self.assertTrue(example.exists(), "缺少 global_rotation_assets.json.example")
        cfg = json.loads(real.read_text(encoding="utf-8"))
        ex = json.loads(example.read_text(encoding="utf-8"))
        self.assertEqual(set(cfg), set(ex))
        self.assertEqual(len(ex["indices"]), 4)
        self.assertEqual(len(ex["etfs"]), 9)


class LiveApiReasonTest(unittest.TestCase):
    def test_portal_surfaces_rotation_reason(self):
        from deck import live_api
        err = gr.RotationInputError("input_missing", "blocked")
        with mock.patch.object(gr, "widget", side_effect=err):
            out = live_api.live_wufu_rotation()
        self.assertFalse(out["ok"])
        self.assertEqual(out["module"]["state"], "blocked")
        self.assertEqual(out["module"]["reason"], "input_missing")


if __name__ == "__main__":
    unittest.main()
