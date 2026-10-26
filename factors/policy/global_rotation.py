# -*- coding: utf-8 -*-
"""factors/policy/global_rotation.py — 跨资产轮动信号（2026-08-14 因子池 P0 落地）

★基于因子池研究（跨资产轮动规格 v1 + 切换优化 + N福研究）：
  级1 a_share_weak：四指数（沪深300/中小综指/创业板指/中证A500）MA10 3/4 投票判 A 股弱市
  级2 global_rotation：弱市时 9 只全球 ETF 代理池 25 日对数加权动量×R² 排名选最强
  定位 = 防守卡（A股弱市→提示加配黄金/债券/现金），非强制调仓。

数据源（因子池缓存，只读）：
  因子池/output/cache/wufu_idx.parquet（4 指数，1847 天）
  因子池/output/cache/wufu_etf.parquet（9 ETF 代理池，1847 天）

★2026-10-26 Task 3：输入与引擎就绪条件显式化。
  - 映射读 config/global_rotation_assets.json（4 指数 + 9 ETF，含支持的列/位置）；
  - 缺引擎、缺文件、缺列、覆盖不足、日期落后、历史不足 → RotationInputError(blocked)；
  - 非正价格/非有限价格 → RotationInputError(error)；
  - 配置标 unsupported 的资产直接 blocked，禁用替代资产静默顶替；
  - 输出 JSON 禁止 NaN/Infinity。

输出：output/global_rotation.json {date, a_share_weak, weak_vote, global_rotation, params}
接入：门户/择时页读本 JSON 显示「防守卡」；17:35 盘后扫描链可调。
"""
import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

CACHE = BASE / "data" / "factorpool" / "output" / "cache"
CONFIG = BASE / "config" / "global_rotation_assets.json"
OUT = BASE / "output" / "global_rotation.json"

MIN_HOLD = 3          # 最小持有期（天）
CONFIRM = 1           # 换仓确认
R2_MIN = 0.4          # 动量×R² 过滤
MA10_WIN = 10
MIN_INDEX_ROWS = MA10_WIN + 1   # MA10 投票所需最少点
MIN_ETF_ROWS = 61               # ret60 所需最少点（60 日收益 + 当日）
MAX_LAG_DAYS = 8                # 输入最新日期落后业务日上限

_SUPPORTS = ("verified", "unverified", "unsupported")


class RotationInputError(ValueError):
    """输入/引擎不满足计算条件。state 仅 blocked（前置缺失）或 error（数据无效）。"""

    def __init__(self, reason, state="blocked", detail=None):
        self.reason = str(reason)
        self.state = state if state in ("blocked", "error") else "error"
        self.detail = None if detail is None else str(detail)
        msg = self.reason if self.detail is None else f"{self.reason}:{self.detail}"
        super().__init__(msg)


def _as_date(value):
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _detect_engines():
    """返回本机可用的 Parquet 引擎名（只需一个）。"""
    found = []
    for name in ("pyarrow", "fastparquet"):
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is not None:
            found.append(name)
    return found


def _read_parquet(path):
    if not _detect_engines():
        raise RotationInputError("engine_unavailable", "blocked")
    try:
        return pd.read_parquet(path)
    except PermissionError:
        raise
    except ImportError:
        raise RotationInputError("engine_unavailable", "blocked")
    except (OSError, ValueError, KeyError) as exc:
        raise RotationInputError("input_unreadable", "error", type(exc).__name__)


def load_config(path=None):
    """读取资产映射；缺文件/结构不符 → blocked，不猜测默认映射。"""
    p = Path(path) if path is not None else CONFIG
    if not p.exists():
        raise RotationInputError("config_missing", "blocked", p.name)
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RotationInputError("config_invalid", "blocked", type(exc).__name__)
    if not isinstance(cfg, dict):
        raise RotationInputError("config_invalid", "blocked", "not_object")
    groups = (("indices", 4), ("etfs", 9))
    seen = set()
    for group, expected in groups:
        items = cfg.get(group)
        if not isinstance(items, list) or len(items) != expected:
            raise RotationInputError("config_invalid", "blocked", group)
        for item in items:
            if not isinstance(item, dict):
                raise RotationInputError("config_invalid", "blocked", group)
            for field in ("key", "name", "column", "column_index", "support"):
                if field not in item:
                    raise RotationInputError("config_invalid", "blocked", group)
            key = item["key"]
            if not isinstance(key, str) or not key or (group, key) in seen:
                raise RotationInputError("config_invalid", "blocked", group)
            seen.add((group, key))
            if item["support"] not in _SUPPORTS:
                raise RotationInputError("config_invalid", "blocked", key)
            col = item["column"]
            idx = item["column_index"]
            if col is not None and not isinstance(col, str):
                raise RotationInputError("config_invalid", "blocked", key)
            if col is None and not isinstance(idx, int):
                raise RotationInputError("config_invalid", "blocked", key)
    return cfg


def _load_panel(input_dir, filename, items, min_rows):
    """只读加载一个面板，返回 (DataFrame[key], items) 或抛 RotationInputError。"""
    path = Path(input_dir) / filename
    if not path.exists():
        raise RotationInputError("input_missing", "blocked", filename)
    try:
        raw = _read_parquet(path)
    except PermissionError:
        raise RotationInputError("permission_denied", "blocked", filename)
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        raise RotationInputError("input_invalid", "error", filename)

    index = pd.to_datetime(raw.index, errors="coerce")
    if pd.isna(index).any():
        raise RotationInputError("input_invalid", "error", filename)
    raw = raw.copy()
    raw.index = index
    raw = raw.sort_index()

    columns = {}
    for item in items:
        if item["support"] == "unsupported":
            raise RotationInputError("asset_unsupported", "blocked", item["key"])
        col = item["column"]
        if col is not None:
            if col not in raw.columns:
                raise RotationInputError("column_missing", "blocked", item["key"])
            series = raw[col]
        else:
            pos = item["column_index"]
            if not isinstance(pos, int) or pos < 0 or pos >= len(raw.columns):
                raise RotationInputError("coverage_insufficient", "blocked", item["key"])
            series = raw[raw.columns[pos]]

        values = pd.to_numeric(series, errors="coerce")
        arr = values.dropna().to_numpy(dtype=float)
        if arr.size and (not np.isfinite(arr).all() or (arr <= 0).any()):
            raise RotationInputError("price_non_positive", "error", item["key"])
        if int(values.notna().sum()) < min_rows:
            raise RotationInputError("history_insufficient", "blocked", item["key"])
        columns[item["key"]] = values

    panel = pd.DataFrame(columns).sort_index()
    if panel.empty:
        raise RotationInputError("input_invalid", "error", filename)
    return panel, items


def _check_lag(panels, as_of):
    latest = min(panel.index.max() for panel in panels)
    lag = (_as_date(as_of) - latest.date()).days
    if lag > MAX_LAG_DAYS:
        raise RotationInputError("input_stale", "blocked", f"lag_{lag}d")
    return latest


def _finite(value):
    if value is None:
        return None
    val = float(value)
    return round(val, 4) if np.isfinite(val) else None


def _momentum_r2(series, window=25):
    """25 日对数加权线性回归：年化动量 × R²（权重 1→2 递增，与因子池 accept16 同口径）"""
    s = series.dropna().tail(window)
    if len(s) < window:
        return None
    y = np.log(s.values.astype(float))
    x = np.arange(len(y))
    w = np.linspace(1, 2, len(y))
    xm = np.average(x, weights=w)
    ym = np.average(y, weights=w)
    cov = np.average((x - xm) * (y - ym), weights=w)
    var = np.average((x - xm) ** 2, weights=w)
    if var < 1e-12:
        return None
    b = cov / var
    a = ym - b * xm
    yhat = a + b * x
    ss_res = np.sum(w * (y - yhat) ** 2)
    ss_tot = np.sum(w * (y - ym) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(b * 252), float(r2)   # 年化动量（log 斜率×252）, R²


def _load_all(input_dir=None, config_path=None, as_of=None):
    cfg = load_config(config_path)
    root = Path(input_dir) if input_dir is not None else CACHE
    idx, idx_items = _load_panel(root, "wufu_idx.parquet", cfg["indices"], MIN_INDEX_ROWS)
    etf, etf_items = _load_panel(root, "wufu_etf.parquet", cfg["etfs"], MIN_ETF_ROWS)
    latest = _check_lag([idx, etf], as_of)
    return idx, idx_items, etf, etf_items, latest


def compute(input_dir=None, out_path=None, as_of=None, config_path=None) -> dict:
    idx, idx_items, etf, etf_items, latest = _load_all(input_dir, config_path, as_of)
    date_str = latest.strftime("%Y-%m-%d")

    # 级1：四指数 MA10 3/4 投票（滞回退出需 ≥3 站上）
    if idx.iloc[-1].isna().any():
        raise RotationInputError("input_invalid", "error", "index_last_row_nan")
    ma10 = idx.rolling(MA10_WIN).mean()
    if ma10.iloc[-1].isna().any():
        raise RotationInputError("history_insufficient", "blocked", "index_ma10")
    below = idx.iloc[-1] < ma10.iloc[-1]
    weak_vote = int(below.sum())
    a_share_weak = weak_vote >= 3

    # 级2：弱市时全球 ETF 动量×R² 排名
    global_rotation = None
    if a_share_weak:
        ma10e = etf.rolling(MA10_WIN).mean()
        cands = []
        for item in etf_items:
            key = item["key"]
            s = etf[key].dropna()
            mom = _momentum_r2(s)
            if not mom:
                continue
            m_ann, r2 = mom
            last_ma = ma10e[key].iloc[-1]
            above_ma10 = bool(s.iloc[-1] > last_ma) if pd.notna(last_ma) else False
            if r2 >= R2_MIN and above_ma10 and np.isfinite(m_ann * r2):
                cands.append((m_ann * r2, key, m_ann, r2))
        if cands:
            cands.sort(key=lambda x: -x[0])
            score, key, m_ann, r2 = cands[0]
            name = next(i["name"] for i in etf_items if i["key"] == key)
            global_rotation = {
                "code": key, "name": name,
                "score": round(score, 4), "momentum_ann": round(m_ann, 4),
                "r2": round(r2, 4), "note": "A股弱市 → 动量×R² 最强全球资产（防守建议）",
            }

    out = {
        "date": date_str,
        "a_share_weak": a_share_weak,
        "weak_vote": weak_vote,
        "global_rotation": global_rotation,
        "params": {"min_hold": MIN_HOLD, "confirm": CONFIRM, "r2_min": R2_MIN, "ma10": MA10_WIN},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    text = json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False)
    target = Path(out_path) if out_path is not None else OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return out


def widget(input_dir=None, as_of=None, config_path=None) -> dict:
    """★2026-08-16 五福轮动门户摆件数据：9 只全球 ETF 代理池常态动量面板（不依赖弱市）。
    供 /api/live/wufu_rotation（门户常显摆件；弱市防守建议仍读 global_rotation.json）。

    ★2026-10-26 Task 3：名称与列映射来自配置，不再按位置猜测；输入不满足时抛
    RotationInputError（blocked/error），由 live_api 转为模块状态。
    """
    idx, idx_items, etf, etf_items, latest = _load_all(input_dir, config_path, as_of)
    ma10e = etf.rolling(MA10_WIN).mean()
    assets = []
    for item in etf_items:
        key = item["key"]
        s = etf[key].dropna()
        ret20 = float(s.iloc[-1] / s.iloc[-21] - 1) if len(s) > 21 else None
        ret60 = float(s.iloc[-1] / s.iloc[-61] - 1) if len(s) > 61 else None
        mom = _momentum_r2(s)
        m_ann, r2 = mom if mom else (None, None)
        last_ma = ma10e[key].iloc[-1]
        above = bool(s.iloc[-1] > last_ma) if pd.notna(last_ma) else False
        assets.append({"name": item["name"], "ret20": _finite(ret20),
                       "ret60": _finite(ret60), "mom_ann": _finite(m_ann),
                       "r2": _finite(r2), "above_ma10": above})
    assets.sort(key=lambda a: -(a["mom_ann"] if a["mom_ann"] is not None else -9))
    return {"date": latest.strftime("%Y-%m-%d"), "assets": assets}


if __name__ == "__main__":
    r = compute()
    print(f"日期 {r['date']} | a_share_weak={r['a_share_weak']}（投票 {r['weak_vote']}/4）")
    if r["global_rotation"]:
        g = r["global_rotation"]
        print(f"全球轮动建议: {g['name']} score={g['score']} mom={g['momentum_ann']:.1%} R²={g['r2']}")
    else:
        print("全球轮动: 无建议（A股非弱市 或 无 ETF 达标）")
    print(f"输出: {OUT}")
