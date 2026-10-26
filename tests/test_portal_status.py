# -*- coding: utf-8 -*-
"""首页模块可用性契约测试（Task 2）。

只使用临时合成文件，不访问真实供应商、不触发数据生成。
"""
import json
import os
import stat
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deck import live_api  # noqa: E402
from deck import portal_status as ps  # noqa: E402
from deck import system_live  # noqa: E402

TODAY = datetime.now().strftime("%Y-%m-%d")
OLD_DAY = "2000-01-01"


class BuildModuleStatusTest(unittest.TestCase):
    def test_contract_fields_and_values(self):
        out = ps.build_module_status(
            state="ready", mode="real", data_date="2026-10-23",
            generated_at="2026-10-23 18:30:00", scope="main",
            reason=None, run_id="run-1")
        self.assertEqual(list(out), ["state", "mode", "data_date", "generated_at",
                                     "scope", "reason", "run_id"])
        self.assertEqual(out["state"], "ready")
        self.assertEqual(out["mode"], "real")
        self.assertEqual(out["data_date"], "2026-10-23")
        self.assertEqual(out["generated_at"], "2026-10-23 18:30:00")
        self.assertEqual(out["scope"], "main")
        self.assertIsNone(out["reason"])
        self.assertEqual(out["run_id"], "run-1")

    def test_all_states_and_modes_accepted(self):
        for state in ("ready", "empty", "missing", "stale", "blocked", "error"):
            for mode in ("demo", "real", "unknown"):
                out = ps.build_module_status(
                    state=state, mode=mode, data_date=None, generated_at=None,
                    scope="unknown", reason="ok", run_id=None)
                self.assertEqual(out["state"], state)
                self.assertEqual(out["mode"], mode)

    def test_invalid_state_and_mode_are_normalized(self):
        out = ps.build_module_status(
            state="processing", mode="prod", data_date=None, generated_at=None,
            scope="unknown", reason=None, run_id=None)
        self.assertEqual(out["state"], "error")
        self.assertEqual(out["mode"], "unknown")
        self.assertEqual(out["reason"], "invalid_state")

    def test_invalid_mode_reason(self):
        out = ps.build_module_status(
            state="ready", mode="prod", data_date=None, generated_at=None,
            scope="unknown", reason=None, run_id=None)
        self.assertEqual(out["mode"], "unknown")
        self.assertEqual(out["reason"], "invalid_mode")

    def test_dates_are_normalized(self):
        out = ps.build_module_status(
            state="ready", mode="real", data_date="20261023",
            generated_at=datetime(2026, 10, 23, 18, 30, 5),
            scope="unknown", reason=None, run_id=None)
        self.assertEqual(out["data_date"], "2026-10-23")
        self.assertEqual(out["generated_at"], "2026-10-23 18:30:05")
        self.assertIsNone(ps.build_module_status(
            state="ready", mode="real", data_date="not-a-date",
            generated_at=None, scope="unknown", reason=None,
            run_id=None)["data_date"])

    def test_reason_and_run_id_do_not_leak_paths(self):
        out = ps.build_module_status(
            state="error", mode="real", data_date=None, generated_at=None,
            scope="C:\\Users\\jack\\secret", reason="/home/jack/apps/secret.json",
            run_id="../../etc/passwd")
        self.assertEqual(out["reason"], "unspecified")
        self.assertEqual(out["scope"], "unspecified")
        self.assertNotIn("jack", json.dumps(out, ensure_ascii=False))
        self.assertNotIn("/", json.dumps(out, ensure_ascii=False))
        self.assertNotIn("\\", json.dumps(out, ensure_ascii=False))

    def test_mode_from_data_kind(self):
        self.assertEqual(ps.mode_from_data_kind("demo"), "demo")
        self.assertEqual(ps.mode_from_data_kind("cache"), "real")
        self.assertEqual(ps.mode_from_data_kind("real"), "real")
        self.assertEqual(ps.mode_from_data_kind("unknown"), "unknown")
        self.assertEqual(ps.mode_from_data_kind(None), "unknown")


class AssessArtifactTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, payload):
        p = self.dir / name
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return p

    def test_missing_file_count_is_null_and_state_missing(self):
        out = ps.assess_artifact(self.dir / "not-there.json",
                                 mode="demo", item_keys=("opportunities",))
        self.assertEqual(out["status"]["state"], "missing")
        self.assertIsNone(out["count"])
        self.assertIsNone(out["payload"])
        self.assertEqual(out["file"], "not-there.json")
        self.assertTrue(out["status"]["reason"].startswith("artifact_"))

    def test_missing_directory_is_missing_not_creatable(self):
        out = ps.assess_latest(self.dir / "absent-dir", "*.json", mode="real",
                               item_keys=("entries",))
        self.assertEqual(out["status"]["state"], "missing")
        self.assertEqual(out["status"]["reason"], "artifact_dir_missing")
        self.assertIsNone(out["count"])

    def test_valid_empty_artifact_is_empty_with_zero(self):
        p = self._write("empty.json", {"date": "2026-10-23", "opportunities": []})
        out = ps.assess_artifact(p, mode="demo", item_keys=("opportunities",))
        self.assertEqual(out["status"]["state"], "empty")
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["data_date"], "2026-10-23")
        self.assertEqual(out["status"]["reason"], "no_items")
        self.assertEqual(out["file"], "empty.json")

    def test_invalid_json_is_error(self):
        p = self.dir / "broken.json"
        p.write_text("{not-json", encoding="utf-8")
        out = ps.assess_artifact(p, mode="real", item_keys=("entries",))
        self.assertEqual(out["status"]["state"], "error")
        self.assertEqual(out["status"]["reason"], "artifact_invalid_json")
        self.assertIsNone(out["count"])
        self.assertIsNone(out["payload"])

    def test_non_dict_payload_is_error(self):
        p = self._write("list.json", [1, 2, 3])
        out = ps.assess_artifact(p, mode="real", item_keys=("entries",))
        self.assertEqual(out["status"]["state"], "error")
        self.assertEqual(out["status"]["reason"], "artifact_schema_mismatch")

    def test_schema_mismatch_is_error(self):
        p = self._write("other.json", {"date": "2026-10-23", "something": 3})
        out = ps.assess_artifact(p, mode="real", item_keys=("entries",))
        self.assertEqual(out["status"]["state"], "error")
        self.assertEqual(out["status"]["reason"], "artifact_schema_mismatch")
        self.assertIsNone(out["count"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root 不受文件权限限制")
    def test_permission_denied_is_blocked(self):
        p = self._write("locked.json", {"entries": [1]})
        os.chmod(p, 0)
        try:
            out = ps.assess_artifact(p, mode="real", item_keys=("entries",))
        finally:
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
        self.assertEqual(out["status"]["state"], "blocked")
        self.assertEqual(out["status"]["reason"], "artifact_permission_denied")
        self.assertIsNone(out["count"])

    def test_stale_artifact_keeps_data_date_and_count(self):
        p = self._write("old.json", {"date": "2026-10-01", "entries": [1, 2, 3]})
        out = ps.assess_artifact(p, mode="real", item_keys=("entries",),
                                 stale_days=3, now=datetime(2026, 10, 23, 12, 0, 0))
        self.assertEqual(out["status"]["state"], "stale")
        self.assertEqual(out["status"]["reason"], "artifact_stale")
        self.assertEqual(out["status"]["data_date"], "2026-10-01")
        self.assertEqual(out["count"], 3)

    def test_fresh_artifact_is_ready(self):
        p = self._write("fresh.json", {"date": "2026-10-23", "entries": [1, 2]})
        out = ps.assess_artifact(p, mode="real", item_keys=("entries",),
                                 stale_days=3, now=datetime(2026, 10, 23, 12, 0, 0))
        self.assertEqual(out["status"]["state"], "ready")
        self.assertIsNone(out["status"]["reason"])
        self.assertEqual(out["count"], 2)

    def test_coverage_insufficient_is_blocked(self):
        p = self._write("thin.json", {"date": "2026-10-23", "entries": [1, 2]})
        out = ps.assess_artifact(p, mode="real", item_keys=("entries",),
                                 min_items=5, now=datetime(2026, 10, 23, 12, 0, 0))
        self.assertEqual(out["status"]["state"], "blocked")
        self.assertEqual(out["status"]["reason"], "coverage_insufficient")
        self.assertEqual(out["count"], 2)

    def test_generated_at_from_payload(self):
        p = self._write("ts.json", {"ts": "2026-10-23 18:31:02", "entries": [1]})
        out = ps.assess_artifact(p, mode="real", item_keys=("entries",))
        self.assertEqual(out["generated_at"], "2026-10-23 18:31:02")
        self.assertEqual(out["status"]["generated_at"], "2026-10-23 18:31:02")

    def test_assess_latest_prefers_newest_file(self):
        old = self._write("part-1.json", {"date": "2026-10-01", "entries": []})
        new = self._write("part-2.json", {"date": "2026-10-23", "entries": [1]})
        past = time.time() - 3600
        os.utime(old, (past, past))
        os.utime(new, (time.time(), time.time()))
        out = ps.assess_latest(self.dir, "part-*.json", mode="real",
                               item_keys=("entries",))
        self.assertEqual(out["file"], "part-2.json")
        self.assertEqual(out["status"]["state"], "ready")
        self.assertEqual(out["data_date"], "2026-10-23")


class ResolveModeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "proj"
        (self.root / "config").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _params(self, text):
        (self.root / "config" / "params.yaml").write_text(text, encoding="utf-8")

    def test_missing_config_is_unknown(self):
        self.assertEqual(ps.resolve_mode(self.root, env={}), "unknown")

    def test_demo_cache_dir_is_demo(self):
        self._params("data:\n  cache_dir: data/demo\n")
        self.assertEqual(ps.resolve_mode(self.root, env={}), "demo")

    def test_default_cache_dir_is_real(self):
        self._params("data:\n  other: 1\n")
        self.assertEqual(ps.resolve_mode(self.root, env={}), "real")

    def test_env_overrides_config(self):
        self._params("data:\n  cache_dir: data/cache\n")
        self.assertEqual(
            ps.resolve_mode(self.root, env={"LWQUANT_CACHE_DIR": "data/demo"}),
            "demo")

    def test_broken_config_is_unknown(self):
        self._params("data: [unclosed\n")
        self.assertEqual(ps.resolve_mode(self.root, env={}), "unknown")


class PortalModulesTest(unittest.TestCase):
    """deck.live_api._portal_modules：把产物组合成首页六态（临时目录，不碰真实数据）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "logs").mkdir()
        (self.root / "output").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, rel, payload):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return p

    def test_all_modules_present_and_absent_is_missing(self):
        modules = live_api._portal_modules("demo", {}, root=self.root)
        self.assertEqual(set(modules), {
            "opp_pool", "pitch", "tech_pitch", "stop_alerts", "forward_track",
            "timing", "traffic_light", "global_rotation", "brief", "chain",
            "api_health", "schedule"})
        for key in ("opp_pool", "pitch", "tech_pitch", "stop_alerts",
                    "forward_track", "timing", "global_rotation"):
            self.assertEqual(modules[key]["state"], "missing", key)
            self.assertEqual(modules[key]["mode"], "demo", key)
        self.assertEqual(modules["opp_pool"]["reason"], "artifact_missing")

    def test_missing_directory_is_distinguished(self):
        empty = Path(self._tmp.name) / "no-such-root"
        modules = live_api._portal_modules("real", {}, root=empty)
        self.assertEqual(modules["opp_pool"]["state"], "missing")
        self.assertEqual(modules["opp_pool"]["reason"], "artifact_dir_missing")

    def test_empty_error_ready_and_stale_are_separated(self):
        self._write("logs/opp_pool_1.json",
                    {"date": TODAY, "opportunities": []})
        (self.root / "logs" / "pitch_v2_1.json").write_text(
            "{broken", encoding="utf-8")
        self._write("logs/tech_pitch_1.json", {"date": TODAY, "entries": [1]})
        self._write("logs/stop_alerts_1.json", {"date": TODAY, "alerts": []})
        self._write("output/traffic_light.json",
                    {"label": "观望", "asof": TODAY})
        self._write("output/global_rotation.json",
                    {"date": OLD_DAY, "assets": [1]})

        modules = live_api._portal_modules("real", {}, root=self.root)

        self.assertEqual(modules["opp_pool"]["state"], "empty")
        self.assertEqual(modules["opp_pool"]["reason"], "no_items")

        self.assertEqual(modules["pitch"]["state"], "error")
        self.assertEqual(modules["pitch"]["reason"], "artifact_invalid_json")

        self.assertEqual(modules["tech_pitch"]["state"], "ready")
        self.assertEqual(modules["tech_pitch"]["data_date"], TODAY)

        self.assertEqual(modules["stop_alerts"]["state"], "empty")

        # traffic_light 有文件但缺 state 字段 → 计算异常（不得当成正常）
        self.assertEqual(modules["traffic_light"]["state"], "error")
        self.assertEqual(modules["traffic_light"]["reason"],
                         "artifact_schema_mismatch")

        self.assertEqual(modules["global_rotation"]["state"], "stale")
        self.assertEqual(modules["global_rotation"]["reason"], "artifact_stale")

    def test_traffic_light_ready_requires_state_field(self):
        self._write("output/traffic_light.json",
                    {"state": "green", "label": "金叉", "asof": TODAY})
        modules = live_api._portal_modules("demo", {}, root=self.root)
        self.assertEqual(modules["traffic_light"]["state"], "ready")
        self.assertEqual(modules["traffic_light"]["data_date"], TODAY)

    def test_brief_chain_health_and_schedule_states(self):
        dash = {
            "brief": {"ok": False},
            "chain": {"ok": True, "latest_td": TODAY,
                      "chain": [{"ok": True}, {"ok": False}]},
            "api_health": {"opp_pool": {"state": "missing", "data_date": None}},
            "schedule": {"items": [], "state": "blocked",
                         "reason": "scheduler_unsupported"},
        }
        modules = live_api._portal_modules("demo", dash, root=self.root)
        self.assertEqual(modules["brief"]["state"], "error")
        self.assertEqual(modules["brief"]["reason"], "compute_failed")
        self.assertEqual(modules["chain"]["state"], "stale")
        self.assertEqual(modules["chain"]["reason"], "chain_lag")
        self.assertEqual(modules["api_health"]["state"], "missing")
        self.assertEqual(modules["api_health"]["reason"], "source_missing")
        self.assertEqual(modules["schedule"]["state"], "blocked")
        self.assertEqual(modules["schedule"]["reason"], "scheduler_unsupported")

    def test_absent_brief_chain_health_schedule(self):
        modules = live_api._portal_modules("demo", {}, root=self.root)
        for key in ("brief", "chain", "api_health", "schedule"):
            self.assertEqual(modules[key]["state"], "missing", key)
            self.assertEqual(modules[key]["reason"], "artifact_missing", key)

    def test_health_schema_mismatch_is_error(self):
        dash = {"api_health": {"opp_pool": {"online": False}}}
        modules = live_api._portal_modules("demo", dash, root=self.root)
        self.assertEqual(modules["api_health"]["state"], "error")
        self.assertEqual(modules["api_health"]["reason"],
                         "artifact_schema_mismatch")

    def test_schedule_invalid_state_falls_back_to_error(self):
        dash = {"schedule": {"items": [], "state": "weird"}}
        modules = live_api._portal_modules("demo", dash, root=self.root)
        self.assertEqual(modules["schedule"]["state"], "error")

    def test_probe_failure_is_error_not_exception(self):
        with mock.patch.object(ps, "assess_latest",
                               side_effect=RuntimeError("boom")):
            modules = live_api._portal_modules("demo", {}, root=self.root)
        self.assertEqual(modules["opp_pool"]["state"], "error")
        self.assertEqual(modules["opp_pool"]["reason"], "status_probe_failed")


class ApiHealthTest(unittest.TestCase):
    """deck.system_live._api_health：区分缺失/空/损坏/陈旧，且保留兼容字段。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for sub in ("logs", "output", "report"):
            (self.root / sub).mkdir()
        self._patch = mock.patch.object(system_live, "BASE", self.root)
        self._patch.start()
        system_live._health_cache.update({"ts": 0.0, "data": None})

    def tearDown(self):
        self._patch.stop()
        system_live._health_cache.update({"ts": 0.0, "data": None})
        self._tmp.cleanup()

    def _reset(self):
        system_live._health_cache.update({"ts": 0.0, "data": None})

    def test_all_sources_missing(self):
        out = system_live._api_health()
        self.assertEqual(len(out), 11)
        for name, row in out.items():
            self.assertEqual(row["state"], "missing", name)
            self.assertEqual(row["reason"], "source_missing", name)
            self.assertFalse(row["online"], name)
            self.assertTrue(row["stale"], name)

    def test_fresh_source_is_ready_with_compat_fields(self):
        (self.root / "output" / "traffic_light.json").write_text(
            json.dumps({"asof": TODAY, "state": "green"}), encoding="utf-8")
        row = system_live._api_health()["traffic_light"]
        self.assertEqual(row["state"], "ready")
        self.assertIsNone(row["reason"])
        self.assertTrue(row["online"])
        self.assertFalse(row["stale"])
        self.assertEqual(row["data_date"], TODAY)
        self.assertEqual(row["stale_h"], 72)
        self.assertIsNotNone(row["age_h"])

    def test_empty_file_is_empty_not_ready(self):
        (self.root / "logs" / "pitch_v2_1.json").write_text(
            "   \n", encoding="utf-8")
        row = system_live._api_health()["pitch_v2"]
        self.assertEqual(row["state"], "empty")
        self.assertEqual(row["reason"], "source_empty")
        self.assertTrue(row["online"])
        self.assertTrue(row["stale"])

    def test_corrupt_json_is_error(self):
        (self.root / "logs" / "pitch_v2_1.json").write_text(
            "{bad", encoding="utf-8")
        row = system_live._api_health()["pitch_v2"]
        self.assertEqual(row["state"], "error")
        self.assertEqual(row["reason"], "source_corrupt_json")
        self.assertTrue(row["online"])

    def test_old_business_date_is_stale_even_if_mtime_fresh(self):
        p = self.root / "output" / "traffic_light.json"
        p.write_text(json.dumps({"asof": OLD_DAY}), encoding="utf-8")
        row = system_live._api_health()["traffic_light"]
        self.assertEqual(row["state"], "stale")
        self.assertEqual(row["reason"], "source_stale")
        self.assertEqual(row["data_date"], OLD_DAY)
        self.assertTrue(row["online"])
        self.assertLess(row["age_h"], 1)

    def test_result_is_cached_within_ttl(self):
        first = system_live._api_health()
        (self.root / "output" / "traffic_light.json").write_text(
            json.dumps({"asof": TODAY}), encoding="utf-8")
        self.assertIs(system_live._api_health(), first)


class NextScheduleDetailTest(unittest.TestCase):
    """deck.system_live._next_schedule_detail：查询不可用 ≠ 没有任务。"""

    def setUp(self):
        system_live._next_sched_cache.update({"ts": 0.0, "data": None})

    def tearDown(self):
        system_live._next_sched_cache.update({"ts": 0.0, "data": None})

    @unittest.skipIf(sys.platform.startswith("win"),
                     "该断言仅适用于非 Windows 环境")
    def test_non_windows_is_blocked_not_empty(self):
        detail = system_live._next_schedule_detail()
        self.assertEqual(detail["state"], "blocked")
        self.assertEqual(detail["reason"], "scheduler_unsupported")
        self.assertEqual(detail["items"], [])
        self.assertEqual(system_live._next_schedule(), [])

    def _run_windows(self, side_effect, tasks=None):
        tasks = tasks if tasks is not None else [("T1", "测试任务")]
        fake_sys = types.SimpleNamespace(platform="win32")
        with mock.patch.object(system_live, "sys", fake_sys), \
                mock.patch.object(system_live, "SCHEDULED_TASKS", tasks), \
                mock.patch.object(system_live, "subprocess") as sp:
            sp.run.side_effect = side_effect
            system_live._next_sched_cache.update({"ts": 0.0, "data": None})
            return system_live._next_schedule_detail()

    @staticmethod
    def _ok(stdout="下次运行时间: 2026/10/27 18:30:00"):
        return types.SimpleNamespace(stdout=stdout, returncode=0)

    def test_windows_all_success_is_ready(self):
        detail = self._run_windows([self._ok()])
        self.assertEqual(detail["state"], "ready")
        self.assertIsNone(detail["reason"])
        self.assertEqual(len(detail["items"]), 1)
        self.assertEqual(detail["items"][0]["name"], "T1")
        self.assertEqual(detail["platform"], "win32")

    def test_windows_partial_failure_is_stale(self):
        detail = self._run_windows(
            [self._ok(), OSError("schtasks missing")],
            tasks=[("T1", "任务一"), ("T2", "任务二")])
        self.assertEqual(detail["state"], "stale")
        self.assertEqual(detail["reason"], "partial_query_failed")
        self.assertEqual(len(detail["items"]), 1)

    def test_windows_all_failures_is_error(self):
        detail = self._run_windows([OSError("boom")])
        self.assertEqual(detail["state"], "error")
        self.assertEqual(detail["reason"], "query_failed")
        self.assertEqual(detail["items"], [])

    def test_windows_no_registered_tasks_is_empty(self):
        detail = self._run_windows([], tasks=[])
        self.assertEqual(detail["state"], "empty")
        self.assertEqual(detail["reason"], "no_tasks")


if __name__ == "__main__":
    unittest.main()
