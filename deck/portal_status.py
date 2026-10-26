# -*- coding: utf-8 -*-
"""deck/portal_status.py — 首页模块可用性契约（Task 2）。

纯函数与只读文件评估：
  - build_module_status：统一六态 + 模式 + 数据日 + 生成时间 + 范围 + 原因码；
  - assess_artifact / assess_latest：从真实产物判定 missing/empty/stale/blocked/error；
  - resolve_mode / mode_from_data_kind：把主系统数据目录映射为 demo/real/unknown。

禁止写入、禁止访问供应商；返回值只含文件名，不含绝对私有路径或原始异常文本。
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

STATES = ("ready", "empty", "missing", "stale", "blocked", "error")
MODES = ("demo", "real", "unknown")

_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")

_DATE_KEYS = ("data_date", "date", "trade_date", "pool_date", "asof", "end_date")
_TS_KEYS = ("generated_at", "updated", "ts", "created_at")


def _safe_code(value, default=None):
    """把原因/范围/运行号收敛为短代码，避免泄露路径或原始异常。"""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if _SAFE_CODE.match(text):
        return text
    return "unspecified"


def _iso_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)),
                    int(match.group(3))).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _iso_ts(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    day = _iso_date(text)
    return f"{day} 00:00:00" if day else None


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    parsed = _iso_ts(value)
    if parsed:
        return datetime.strptime(parsed, "%Y-%m-%d %H:%M:%S")
    return datetime.now()


def build_module_status(*, state, mode, data_date, generated_at,
                        scope, reason, run_id) -> dict:
    """统一模块状态。非法 state 归一为 error，非法 mode 归一为 unknown。"""
    if state not in STATES:
        _state, _reason = "error", "invalid_state"
    elif mode not in MODES:
        _state, _reason = state, "invalid_mode"
    else:
        _state, _reason = state, _safe_code(reason)
    return {
        "state": _state,
        "mode": mode if mode in MODES else "unknown",
        "data_date": _iso_date(data_date),
        "generated_at": _iso_ts(generated_at),
        "scope": _safe_code(scope, "unknown") or "unknown",
        "reason": _reason,
        "run_id": _safe_code(run_id),
    }


def extract_data_date(payload):
    """取产物中的业务数据日（首个可解析日期），无则返回 None。"""
    if not isinstance(payload, dict):
        return None
    return next((_iso_date(payload.get(k)) for k in _DATE_KEYS
                 if _iso_date(payload.get(k))), None)


def extract_generated_at(payload):
    """取产物中的生成时间（首个可解析时间戳），无则返回 None。"""
    if not isinstance(payload, dict):
        return None
    return next((_iso_ts(payload.get(k)) for k in _TS_KEYS
                 if _iso_ts(payload.get(k))), None)


def mode_from_data_kind(kind) -> str:
    return {"demo": "demo", "cache": "real", "real": "real"}.get(kind, "unknown")


def resolve_mode(root, *, env=None) -> str:
    """按 env > config/params.yaml data.cache_dir > data/cache 判定 demo/real。

    配置不存在或无法解析时返回 unknown，不假设为真实数据。
    """
    env = os.environ if env is None else env
    raw = env.get("LWQUANT_CACHE_DIR")
    if not raw:
        cfg = Path(root) / "config" / "params.yaml"
        if not cfg.is_file():
            return "unknown"
        try:
            import yaml
            config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        except Exception:
            return "unknown"
        data = config.get("data") if isinstance(config, dict) else None
        raw = data.get("cache_dir") if isinstance(data, dict) else None
        if not raw:
            raw = "data/cache"
    parts = str(raw).replace("\\", "/").lower().split("/")
    return "demo" if "demo" in parts else "real"


def _missing(mode, scope, reason, file_name, run_id):
    status = build_module_status(state="missing", mode=mode, data_date=None,
                                 generated_at=None, scope=scope,
                                 reason=reason, run_id=run_id)
    return {"status": status, "payload": None, "count": None,
            "data_date": None, "generated_at": None, "file": file_name}


def assess_artifact(path, *, mode="unknown", item_keys=(), count_key=None,
                    data_date_keys=_DATE_KEYS, generated_at_keys=_TS_KEYS,
                    scope="unknown", stale_days=None, min_items=None,
                    now=None, run_id=None) -> dict:
    """评估单个 JSON 产物。返回状态、原始 payload、数量、数据日与文件名。

    item_keys 给定时必须命中其一，否则视为结构不匹配（error）。
    """
    file_name = Path(path).name if path else None
    if path is None:
        return _missing(mode, scope, "artifact_missing", file_name, run_id)
    p = Path(path)
    if not p.exists():
        reason = "artifact_dir_missing" if not p.parent.exists() else "artifact_missing"
        return _missing(mode, scope, reason, file_name, run_id)
    if not p.is_file():
        return _missing(mode, scope, "artifact_not_file", file_name, run_id)

    try:
        raw = p.read_text(encoding="utf-8")
    except PermissionError:
        status = build_module_status(state="blocked", mode=mode, data_date=None,
                                     generated_at=None, scope=scope,
                                     reason="artifact_permission_denied",
                                     run_id=run_id)
        return {"status": status, "payload": None, "count": None,
                "data_date": None, "generated_at": None, "file": file_name}
    except OSError:
        status = build_module_status(state="error", mode=mode, data_date=None,
                                     generated_at=None, scope=scope,
                                     reason="artifact_unreadable", run_id=run_id)
        return {"status": status, "payload": None, "count": None,
                "data_date": None, "generated_at": None, "file": file_name}

    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        status = build_module_status(state="error", mode=mode, data_date=None,
                                     generated_at=None, scope=scope,
                                     reason="artifact_invalid_json", run_id=run_id)
        return {"status": status, "payload": None, "count": None,
                "data_date": None, "generated_at": None, "file": file_name}

    if not isinstance(payload, dict):
        status = build_module_status(state="error", mode=mode, data_date=None,
                                     generated_at=None, scope=scope,
                                     reason="artifact_schema_mismatch", run_id=run_id)
        return {"status": status, "payload": None, "count": None,
                "data_date": None, "generated_at": None, "file": file_name}

    count = None
    if item_keys:
        found = next((k for k in item_keys if k in payload), None)
        value = payload.get(found) if found else None
        if found is None or not isinstance(value, (list, dict)):
            status = build_module_status(state="error", mode=mode, data_date=None,
                                         generated_at=None, scope=scope,
                                         reason="artifact_schema_mismatch",
                                         run_id=run_id)
            return {"status": status, "payload": payload, "count": None,
                    "data_date": None, "generated_at": None, "file": file_name}
        count = len(value)
    elif count_key:
        value = payload.get(count_key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            count = int(value)

    data_date = extract_data_date(payload)
    generated_at = extract_generated_at(payload)

    state, reason = "ready", None
    if payload.get("ok") is False:
        state, reason = "error", "compute_failed"
    elif stale_days is not None and not data_date:
        state, reason = "blocked", "data_date_missing"
    if state == "ready" and stale_days is not None and data_date:
        age_days = (_as_datetime(now).date()
                    - datetime.strptime(data_date, "%Y-%m-%d").date()).days
        if age_days > int(stale_days):
            state, reason = "stale", "artifact_stale"
    if state == "ready" and count == 0:
        state, reason = "empty", "no_items"
    if state == "ready" and min_items is not None and count is not None \
            and count < int(min_items):
        state, reason = "blocked", "coverage_insufficient"

    status = build_module_status(state=state, mode=mode, data_date=data_date,
                                 generated_at=generated_at, scope=scope,
                                 reason=reason, run_id=run_id)
    return {"status": status, "payload": payload, "count": count,
            "data_date": data_date, "generated_at": generated_at,
            "file": file_name}


def assess_latest(root, pattern, *, mode="unknown", run_id=None, **kwargs) -> dict:
    """在 root 下按 mtime 取最新匹配文件后评估；无文件保持 missing。"""
    base = Path(root)
    if not base.is_dir():
        return _missing(mode, kwargs.get("scope", "unknown"),
                        "artifact_dir_missing", None, run_id)
    try:
        files = [p for p in base.glob(pattern) if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime)
    except OSError:
        status = build_module_status(state="error", mode=mode, data_date=None,
                                     generated_at=None,
                                     scope=kwargs.get("scope", "unknown"),
                                     reason="artifact_unreadable", run_id=run_id)
        return {"status": status, "payload": None, "count": None,
                "data_date": None, "generated_at": None, "file": None}
    if not files:
        return _missing(mode, kwargs.get("scope", "unknown"),
                        "artifact_missing", None, run_id)
    return assess_artifact(files[-1], mode=mode, run_id=run_id, **kwargs)


def readonly_data_date(cache_dir=None):
    """Latest observed bar date, not a claim of full-market completeness.

    Never initialize schemas or create SQLite sidecars. Active WAL inputs are
    withheld rather than read as an immutable snapshot that omits pending rows.
    """
    import sqlite3
    if cache_dir is None:
        from data.cache import _resolve_cache_dir
        cache_dir = _resolve_cache_dir()
    root = Path(cache_dir).resolve()
    if not root.is_dir():
        return None
    paths = [root / 'bars.db', root / 'bars_incr.db']
    paths.extend(sorted(root.glob('bars_incr_*.db'))[-3:])
    if any(Path(str(p) + '-wal').exists() for p in paths):
        return None
    dates = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            con = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=2)
            try:
                row = con.execute('SELECT MAX(date) FROM daily_bar').fetchone()
                value = _iso_date(row[0]) if row else None
                if value:
                    dates.append(value)
            finally:
                con.close()
        except sqlite3.Error:
            return None
    return max(dates) if dates else None
