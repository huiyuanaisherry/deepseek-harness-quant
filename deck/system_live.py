# -*- coding: utf-8 -*-
"""deck/system_live.py — 实时系统状态聚合（2026-08-10 用户需求 1）

供 /api/system_live 返回实时 JSON（dashboard_live.html 每 5 秒轮询）：
  1. databases: 各数据库心跳（可连接 + 最近交易日）
  2. dev_auto: 最近一次运行日志尾部（正在干什么）
  3. scheduled: 计划任务下次运行时间
  4. api_health: 各 API 端点存活
  5. deck: 自身状态
"""
import json
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# deck 既可作为包（deck.system_live）也可作为顶层模块（deck_server 直接 import system_live）加载
try:
    from . import portal_status as _ps
except ImportError:
    import portal_status as _ps

DBS = {
    "bars": r"data/cache/bars.db",
    "finance": r"data/cache/finance.db",
    "finance_quality": r"data/cache/finance_quality.db",
    "minute": r"data/cache/minute.db",
    "hist_mv": r"data/cache/hist_mv.db",
}

SCHEDULED_TASKS = [
    ("LWQuant-DevDriver", "每 4h 巡检"),
    ("LWQuant-AfterCloseScan", "17:35 盘后机会扫描"),
    ("LWQuant-FactorDaily", "19:15 因子池"),
    ("LWQuant-DailyPipeline", "18:30 每日全链"),
    ("LWQuant-DeckGuard", "每 30min 守护"),
]


_db_cache = {"ts": 0, "data": None}


def _probe_one(name, path):
    """单个库探测：只读+immutable 连接（不等待写锁，立即返回）"""
    import sqlite3
    t0 = time.time()
    try:
        # ★2026-08-10：mode=ro&immutable=1 → 只读快照连接，不等写锁（库被占用也能即时探测）
        uri = f"file:{path}?mode=ro&immutable=1"
        con = sqlite3.connect(uri, uri=True, timeout=0.2)
        tabs = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tname = tabs[0][0] if tabs else "?"
        try:
            n = con.execute(f"SELECT MAX(rowid) FROM {tname}").fetchone()[0]
        except Exception:
            n = None
        con.close()
        return {name: {"online": True, "rows": n, "tables": len(tabs),
                       "ms": round((time.time() - t0) * 1000)}}
    except Exception as e:
        return {name: {"online": False, "error": str(e)[:50],
                       "ms": round((time.time() - t0) * 1000)}}


def _db_health() -> dict:
    """数据库心跳（★2026-08-10：5 库并行探测 + 0.8s 超时 + 30s 缓存，API 毫秒级响应；
    库被占锁时标记"占用中"而非阻塞等待）"""
    from concurrent.futures import ThreadPoolExecutor
    now = time.time()
    if _db_cache["data"] is not None and now - _db_cache["ts"] < 30:
        return _db_cache["data"]
    out = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_probe_one, name, path): name
                   for name, path in DBS.items()}
        for fut in futures:
            try:
                out.update(fut.result(timeout=1.5))
            except Exception as e:
                out[futures[fut]] = {"online": False, "error": "探测超时",
                                     "ms": 1500}
    _db_cache["ts"] = now
    _db_cache["data"] = out
    return out


def _dev_auto_tail(n=8) -> list:
    """dev_auto 最近运行日志尾部（显示系统在干什么）"""
    for p in (BASE / "logs" / "dev_auto.log", BASE / "logs" / "dev_auto_console.log"):
        if p.exists():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                return lines[-n:]
            except Exception:
                pass
    return []


_sched_cache = {"ts": 0, "data": None}


def _scheduled() -> dict:
    """计划任务下次运行时间（5 分钟缓存，schtasks 慢会阻塞 API）"""
    now = time.time()
    if _sched_cache["data"] is not None and now - _sched_cache["ts"] < 300:
        return _sched_cache["data"]
    out = {}
    for name, desc in SCHEDULED_TASKS:
        try:
            r = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"],
                               capture_output=True, text=True, errors="replace",
                               encoding="gbk", timeout=8)
            m = re.search(r"下次运行时间:\s*(.+)", r.stdout)
            out[name] = {"desc": desc, "next": m.group(1).strip() if m else "—"}
        except Exception as e:
            out[name] = {"desc": desc, "next": f"ERR {str(e)[:30]}"}
    _sched_cache["ts"] = now
    _sched_cache["data"] = out
    return out


_health_cache = {"ts": 0.0, "data": None}


def _api_health() -> dict:
    """对 Deck 自身各 API 端点做存活探测（本进程直接读文件更快）

    ★2026-10-26 Task 2：区分"接口可达（online）"与"数据可用（state）"：
      - missing：文件未生成；
      - empty：文件为空；
      - error：JSON 损坏/不可读；
      - stale：能解析但业务数据日或 mtime 超阈值；
      - ready：可用。
    可用性优先按产物内的业务数据日判断（touch 文件不能恢复新鲜）；
    保留原 online/age_h/stale_h/stale 字段兼容旧页面。
    """
    import glob
    now = time.time()
    if _health_cache["data"] is not None and now - _health_cache["ts"] < 60:
        return _health_cache["data"]
    checks = {
        "pitch_v2": ("logs/pitch_v2_*.json", 48),
        "opp_pool": ("logs/opp_pool_*.json", 48),
        "beneish": ("logs/beneish_report*.json", 24 * 7),      # 月度报告，7 天内都新鲜
        "sim_tracks": ("logs/sim_tracks*.json", 24 * 7),        # 样本跟踪低频
        "pitch_track": ("logs/pitch_track_pool_*.json", 48),
        "regime": ("output/dynamic_regime.json", 72),
        "traffic_light": ("output/traffic_light.json", 72),   # ★2026-08-14 择时红绿灯
        "signal": ("output/daily_signal_*.json", 48),          # ★#351 时间戳文件（无戳旧版残留勿用）
        "audit": ("report/data_audit_report_*.json", 72),       # ★F2：时间戳文件名 glob
        "factor_pool": ("report/factor_pool_report.json", 72),
        "pool_layers": ("output/pool_layers_*.json", 48),       # ★#351 时间戳文件
    }
    out = {}
    for name, (pat, stale_h) in checks.items():
        full = str(BASE / pat)
        if "*" in pat:
            files = sorted(glob.glob(full))
        else:
            files = [full] if Path(full).exists() else []
        if not files:
            out[name] = {"online": False, "age_h": None, "stale_h": stale_h,
                         "stale": True, "state": "missing",
                         "reason": "source_missing", "data_date": None}
            continue
        latest = Path(files[-1])
        try:
            age = now - latest.stat().st_mtime
        except OSError:
            age = None
        age_h = round(age / 3600, 1) if age is not None else None
        data_date = None
        state, reason = "ready", None
        try:
            raw = latest.read_text(encoding="utf-8")
            if not raw.strip():
                state, reason = "empty", "source_empty"
            else:
                payload = json.loads(raw)
                data_date = _ps.extract_data_date(payload)
                if data_date:
                    day_age = (datetime.now().date()
                               - datetime.strptime(data_date, "%Y-%m-%d").date()).days
                    if day_age * 24 > stale_h:
                        state, reason = "stale", "source_stale"
                elif age is not None and age > stale_h * 3600:
                    state, reason = "stale", "source_stale"
        except (ValueError, UnicodeError):
            state, reason = "error", "source_corrupt_json"
        except OSError:
            state, reason = "error", "source_unreadable"
        out[name] = {"online": True, "age_h": age_h, "stale_h": stale_h,
                     "stale": state != "ready", "state": state,
                     "reason": reason, "data_date": data_date}
    _health_cache.update({"ts": now, "data": out})
    return out



def _deck_pid() -> int:
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace", timeout=15)
        for line in r.stdout.splitlines():
            if ":8787" in line and "LISTENING" in line:
                return int(line.split()[-1])
    except Exception:
        pass
    return 0


def _activity_feed(minutes: int = 60) -> list:
    """★2026-08-10 实时活动流：logs/ 目录最近 N 分钟修改的产出文件（显示系统在干活）"""
    import glob
    now = time.time()
    items = []
    for pat in ("logs/*.json", "logs/*.md", "logs/*.csv", "output/*.json", "report/*.json"):
        for p_str in glob.glob(str(BASE / pat)):
            try:
                p = Path(p_str)
                mt = p.stat().st_mtime
                age = now - mt
                if age <= minutes * 60:
                    items.append({
                        "file": p.name, "age_min": round(age / 60, 1),
                        "ts": time.strftime("%H:%M:%S", time.localtime(mt)),
                    })
            except Exception:
                pass
    items.sort(key=lambda x: x["age_min"])
    return items[:15]


_next_sched_cache = {"ts": 0.0, "data": None}


def _next_schedule_detail() -> dict:
    """计划任务查询明细：{items, state, reason}。

    ★2026-10-26 Task 2：把"查询不可用"与"没有任务"分开表达——
    非 Windows 环境无 schtasks → blocked/scheduler_unsupported；
    全部查询失败 → error/query_failed；查询成功但无任务 → empty/no_tasks；
    部分失败 → stale/partial_query_failed。
    旧 `_next_schedule()` 仍返回 items 列表以兼容既有调用方。
    """
    now = time.time()
    if _next_sched_cache["data"] is not None and now - _next_sched_cache["ts"] < 300:
        return _next_sched_cache["data"]
    if not sys.platform.startswith("win"):
        detail = {"items": [], "state": "blocked",
                  "reason": "scheduler_unsupported", "platform": sys.platform}
        _next_sched_cache.update({"ts": now, "data": detail})
        return detail
    out = []
    errors = 0
    for name, desc in SCHEDULED_TASKS:
        try:
            r = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"],
                               capture_output=True, text=True, errors="replace",
                               encoding="gbk", timeout=8)
            m = re.search(r"下次运行时间:\s*(.+)", r.stdout)
            if not m:
                errors += 1
                continue
            nxt = m.group(1).strip()
            # ★容错解析：拆分数字（兼容 2026/8/14 10:00:00 和 2026-08-14 10:00:00）
            parts = re.findall(r"\d+", nxt)
            if len(parts) >= 5:
                y, mo, d, h, mi = (int(parts[0]), int(parts[1]), int(parts[2]),
                                   int(parts[3]), int(parts[4]))
                s = int(parts[5]) if len(parts) >= 6 else 0
                try:
                    nxt_dt = datetime(y, mo, d, h, mi, s)
                    mins = round((nxt_dt - datetime.now()).total_seconds() / 60, 0)
                    out.append({"name": name, "desc": desc, "next": nxt,
                                "mins_left": int(mins)})
                except Exception:
                    out.append({"name": name, "desc": desc, "next": nxt,
                                "mins_left": None})
            else:
                out.append({"name": name, "desc": desc, "next": nxt,
                            "mins_left": None})
        except Exception:
            errors += 1
            continue
    if out and not errors:
        state, reason = "ready", None
    elif out:
        state, reason = "stale", "partial_query_failed"
    elif errors:
        state, reason = "error", "query_failed"
    else:
        state, reason = "empty", "no_tasks"
    detail = {"items": out, "state": state, "reason": reason,
              "platform": sys.platform}
    _next_sched_cache.update({"ts": now, "data": detail})
    return detail


def _next_schedule() -> list:
    """★2026-08-10 距下次各计划任务倒计时（分钟）；兼容旧调用方，仅返回 items。"""
    return _next_schedule_detail().get("items") or []



_cache = {"ts": 0.0, "data": None}


def collect() -> dict:
    """系统实时状态聚合（★2026-08-10 性能：10s 短缓存——页面 5s 轮询降频，避免每次 1.6s 全量探测）"""
    import time as _t
    now = _t.time()
    if _cache["data"] is not None and now - _cache["ts"] < 10:
        _cache["data"]["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return _cache["data"]
    out = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "databases": _db_health(),
        "dev_auto_tail": _dev_auto_tail(),
        "scheduled": _scheduled(),
        "api_health": _api_health(),
        "deck_pid": _deck_pid(),
        "activity_feed": _activity_feed(),      # ★实时活动流
        "next_schedule": _next_schedule(),      # ★倒计时
    }
    _cache.update({"ts": now, "data": out})
    return out


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=1))
