# 门户首页数据依赖审查（2026-10-26）

> 对应计划：`docs/superpowers/plans/2026-10-26-portal-real-data-for-trae.md` Task 1。
> 本报告只做只读核查，不运行旧全量流水线，不联网采集，不修改演示库、六股快照和私有配置。
> 路径一律使用仓库相对路径；不含 Token、Cookie、模型 Key、私有配置正文。

## 1. 执行基线

| 项目 | 实测值 | 说明 |
| --- | --- | --- |
| 仓库 | `deepseek-harness-quant` | 本机路径 `…/AI_Workbench/deepseek-harness-quant` |
| 分支 | `codex/privacy-provider-settings` | 只读核查 |
| HEAD | `b4f3de6`（docs: plan portal real data integration for Trae） | 工作区 clean |
| 本机 Python | 3.9.6；pandas 2.3.3；numpy 2.0.2 | 无 `.venv`、无 pyarrow、无 fastparquet |
| 本机 Node | v24.20.0 | 前端契约测试用 |
| 8787 监听 | PID 18928，`IPv4 127.0.0.1:8787`，进程为 `python -m http.server` | **不是**量化门户服务；不能据此判断门户在线 |

Windows 目标机（LAPTOP-9QL895HA / 100.123.203.13，WSL 用户 jack，项目 `/home/jack/apps/deepseek-harness-quant`）的服务 PID、`.venv` 内容、`data/real-smoke/` 快照与私有配置无法从本机核对，见第 7 节。

## 2. 首页模块依赖表

页面文件：`ui_v2/pages/portal.html`；聚合接口：`/api/live/portal_dash` → `deck/live_api.py: live_portal_dash()`；五福轮动独立接口：`/api/live/wufu_rotation` → `deck/live_api.py: live_wufu_rotation()`；实时行情独立接口：`/api/live/realtime` → `deck/live_api.py: live_realtime()`。

### 2.1 摘要（`summary-box`）

| 环节 | 实际依赖 |
| --- | --- |
| 原始数据 | 择时四维输入见 2.2；健康检查文件见 2.10 |
| 计算入口 | `factors/policy/timing_system.py`（择时产物） |
| 输出路径 | `output/timing_system.json`、`output/timing_system_<ts>.json` |
| 读取函数 | `live_portal_dash()` → `live_timing_dash()`；`_api_health()` |
| 页面字段 | `timing.timing.level`、`timing.timing.score`、`data_semantic`、`api_health`、`timing.timing.temp_zone/reason` |

现状：本机 `output/` 不存在，`live_timing_dash()` 在无文件时仍返回 `ok: true, ts`；页面回退为“择时 — · — 分”，同时 `data_semantic` 硬编码“18:30 更新”的确定承诺（见第 4 节）。

### 2.2 择时（`timing-box`）

| 环节 | 实际依赖 |
| --- | --- |
| 原始数据 | `data/cache/bars.db`（政策/宽度/情绪）、`data/factorpool/output/market_snapshot_ext*.json`、`market_emotion_temp*.json`、`crowding_*.json`、宏观 `daily_signal` 的 `regime_label`、EPU 月度政策数据 |
| 计算入口 | `factors/policy/timing_system.py: evaluate()`，权重政策 40% + 宏观 25% + 情绪 20% + 宽度 15% |
| 输出路径 | `output/timing_system_<ts>.json` + 固定名 `output/timing_system.json` |
| 读取函数 | `live_api.py: live_timing_dash()`（glob 最新 `timing_system_*.json`） |
| 页面字段 | `d.timing.timing.level/score/date/temp_zone/reason` |

现状：`evaluate()` 在多个维度缺数据时回退“中性 50”，因此缺输入也可能产出可展示分数，而非 blocked（见第 4 节）。计算入口本身可运行，但依赖全市场宽度与外部因子池。

### 2.3 择时趋势（`traffic-light-box`）

| 环节 | 实际依赖 |
| --- | --- |
| 原始数据 | 沪深300 月度收盘（`data/cache/bars.db` 的 `SH.000300`，或 `output/hs300_monthly.parquet`）；缺失时 `_ensure_parquet()` 会调 baostock 联网 |
| 计算入口 | `data/traffic_light.py`，MA6/MA12 月度均线，`min_periods=3/6`，窗口近 24 个月 |
| 输出路径 | `output/traffic_light.json` |
| 读取函数 | `live_portal_dash()` 读取最新 `traffic_light*.json` |
| 页面字段 | `traffic_light.state/ratio/color/label/ma6/ma12/hs300/asof/last_cross/backtest/history` |

现状：本机 `output/traffic_light.json` 不存在；页面只有 `if (tlBox && tl.state)` 分支，无 `else`，缺 `state` 时永久停留“加载中…”（见第 4 节）。`history` 用于画 MA6/MA12 双线，需 ≥2 个点，否则显示“数据积累中”。

### 2.4 五福轮动（`wufu-box`）

| 环节 | 实际依赖 |
| --- | --- |
| 原始数据 | `data/factorpool/output/cache/wufu_idx.parquet`（四指数：沪深300、中小综指、创业板指、中证A500）、`wufu_etf.parquet`（九 ETF 按位置映射） |
| 计算入口 | `factors/policy/global_rotation.py: compute()` / `widget()` |
| 输出路径 | `output/global_rotation.json` |
| 读取函数 | `live_api.py: live_wufu_rotation()` → `global_rotation.widget()`，再合并 `output/global_rotation.json` |
| 页面字段 | `loadWufu()` 读取的资产名、动量、R²、ret60、score、params |

现状：本机无 `data/factorpool/`，且无 Parquet 引擎，`widget()` 直接抛异常，接口返回 `error` 且 `assets=[]`。即使安装 pyarrow，仍缺四指数/九 ETF 的实际 Parquet 与覆盖校验，不能视为自动恢复（Task 3 处理）。

### 2.5 KPI 五块（`kpi-box`）

| KPI | 原始数据 | 计算入口 | 输出路径 | 读取函数 | 页面字段 |
| --- | --- | --- | --- | --- | --- |
| 机会池 | `bars.db`、`finance.db`、`quality`、外部因子池 `data/factorpool/output/daily_scores`、manifest/badges/auction/hist_mv | `factors/opportunities/scan.py` | `logs/opp_pool_*.json` | `live_api.py: live_pools()` | `pools.opp_pool.n` |
| Pitch 长线 | 最新 `logs/opp_pool_*.json`、`stock_risk_map*.json`、`beneish_report*.json`、`pitch_priority_badges_*.json` | `factors/opportunities/pitch_v2.py` | `logs/pitch_v2_*.json` | `live_pools()` | `pools.pitch.n` |
| Pitch 短线 | `data/cache/bars.db` + 最近 3 个增量库 | `factors/opportunities/tech_pitch_v3.py` | `logs/tech_pitch_*.json`，并复制到 `deck/tech_pitch_*.json` | `live_pools()` | `pools.tech_pitch.n` |
| 远期池 | 跟踪池产物 | `strategy/` 跟踪链 | `logs/pitch_track_pool_*.json` | `live_pools()` | `pools.forward_track.n` |
| 止损预警 | 最新持仓 `logs/portfolio*.json` | `strategy/portfolio.py` + 止损引擎 | `logs/stop_alerts_*.json` | `live_pools()` | `pools.stop_alerts.held_near` |

现状：本机 `logs/` 不存在，五个 KPI 全部回退为 0，同时接口顶层 `ok: true`。0 与“未计算”不可区分（Task 2 处理）。`scan.py` 的覆盖阈值与硬编码日期见第 4 节。

### 2.6 实时行情（`rt-box`）

| 环节 | 实际依赖 |
| --- | --- |
| 原始数据 | akshare 新浪全市场实时快照（`stock_zh_a_spot()`），60s 内存缓存 |
| 计算入口 | 无持久化计算，`live_realtime()` 现场抓取 |
| 输出路径 | 无文件，仅内存缓存 |
| 读取函数 | `live_api.py: live_realtime()` |
| 页面字段 | 涨跌家数、涨幅、成交额等 |

现状：需要外网与 akshare 权限；失败时若有缓存则标 `stale`，否则 `ok: false`。本检查不触发该接口。

### 2.7 跨资产轮动防守（`global-rot-box`）

| 环节 | 实际依赖 |
| --- | --- |
| 原始数据 | 同 2.4 的 `wufu_idx.parquet` / `wufu_etf.parquet` |
| 计算入口 | `global_rotation.compute()`，四指数 MA10 弱市投票 + 避险资产动量×R² |
| 输出路径 | `output/global_rotation.json` |
| 读取函数 | `live_portal_dash()` 合并 `live_wufu_rotation()` |
| 页面字段 | `global_rotation.a_share_weak/weak_vote/date/params/g.name/score` |

现状：无产物时默认隐藏（`display:none`），隐藏即“无提示”，无法区分“市场不弱”和“没算”。

### 2.8 今日要点（`brief-box`）

| 环节 | 实际依赖 |
| --- | --- |
| 原始数据 | 择时、日历、大小盘分化、健康扫描、验证进度、止盈、组合风险等多源产物 |
| 计算入口 | 无单一入口，`live_brief()` 现场聚合 |
| 输出路径 | 读取多个 `logs/`、`output/` 文件，无独立输出 |
| 读取函数 | `live_api.py: live_brief()` |
| 页面字段 | `brief.items`、`brief.n`、`brief.date` |

现状：各块 `except Exception: pass`，无要点时返回 `ok: true, n: 0, items: []`，无法说明“哪部分未分析”。

### 2.9 系统运行状态（`sys-box`）

| 环节 | 实际依赖 |
| --- | --- |
| 原始数据 | Windows `schtasks` 输出；`data/cache/{bars,finance,finance_quality,minute,hist_mv}.db` |
| 计算入口 | 无，`deck/system_live.py` 现场查询 |
| 输出路径 | 无 |
| 读取函数 | `system_live.py: _scheduled()`、`_next_schedule()`、`_deck_pid()` |
| 页面字段 | 计划任务列表、下一运行时间、服务 PID |

现状：`schtasks` 使用 `encoding="gbk"`，失败或无匹配时 `continue`，最终返回空数组；WSL 下不可用。`_deck_pid()` 用 `netstat -ano` 查 8787，仅 Windows 有效。

### 2.10 API 接口状态（`api-box`）

| 环节 | 实际依赖 |
| --- | --- |
| 原始数据 | 11 项数据文件（行情、财务、分钟、因子池等）的 glob 命中与 mtime |
| 计算入口 | 无，`system_live.py: _api_health()` 现场检查 |
| 输出路径 | 无 |
| 读取函数 | `_api_health()` |
| 页面字段 | `api_health[key].online/stale/age_h` |

现状：缺文件即 `online: false, stale: true`，与“文件存在但过期”混为一谈；页面据此统计“N 项滞后”。接口可达性（33/36 在线）与文件健康不是同一指标，当前页面未区分。

### 2.11 决策链（`chain-box`）

| 环节 | 实际依赖 |
| --- | --- |
| 原始数据 | 13 个环节产物：观察池、新择时、今日信号、竞价信号、机会池、Pitch 长线/短线、持仓、止盈引擎、风控、远期池、实盘裁决、分钟数据 |
| 计算入口 | 各环节独立脚本 |
| 输出路径 | `logs/*`、`output/*`、`data/cache/minute.db` |
| 读取函数 | `live_api.py: live_chain()`（按 glob 检测） |
| 页面字段 | 环节名、`ok`、时间、文件 |

现状：单环节缺文件时该环节 `ok: false`，但聚合顶层仍 `ok: true`，页面无法从顶层判断整链是否完整。

## 3. 数据契约核对

| 检查项 | 结论 | 证据 |
| --- | --- | --- |
| 代码格式 | `000938.SZ`（6 位数字 + 交易所后缀） | 本机 `data/cache/stock_list.csv` 内容格式；`scan.py` 以 `ts_code` 查询 |
| 复权基准 | 行情读取 `adjust='qfq'`；缓存按 `(code, date, adjust)` 主键存 `none/qfq/hfq`；真实样本同时写 raw(none) 与 qfq | `factors/opportunities/scan.py`；`data/cache.py: put_daily(adjust=...)`；`data/real_data_sample.py: prepare_bars()` |
| 单位 | tushare/tushare_backup 的 amount 为千元、volume 为手；baostock/akshare 为元、股。消费端必须先经 `normalize_units()`：amount ×1000、volume ×100 | `data/cache.py` 注释与 `normalize_units()`；`scan.py` 对 tushare 系 ×1000 |
| 财务披露时间 | 校验要求 `ann_date/end_date ≤ as_of`、`ann_date ≥ end_date`，按 `end_date/ann_date` 去重保留最新 | `data/real_data_sample.py: validate_finance()` |
| 择时最小历史 | 四维评分依赖全市场宽度与外部因子池；缺数据回退中性 50，非算法窗口固定值 | `factors/policy/timing_system.py: evaluate()` |
| 择时趋势最小历史 | MA6/MA12 月度均线，`min_periods` 分别为 3/6；展示近 24 个月 | `data/traffic_light.py` |
| 五福轮动最小历史 | `_momentum_r2(window=25)` 需 ≥25 个非空点；MA10 投票需 ≥11 点（`MA10_WIN+1`）；ret60 需 ≥61 点；代码按面板级 `MIN_INDEX_ROWS=11`、`MIN_ETF_ROWS=61` 校验，不足即 blocked | `factors/policy/global_rotation.py`；`tests/test_global_rotation_inputs.py` |
| 指数/ETF 资产范围 | 四指数（沪深300、中小综指、创业板指、中证A500）列名见于旧代码；九 ETF 缓存列名为 GBK 乱码，按位置映射，名称含恒指/中证500 等，与计划提到的“黄金/纳指/标普500/日经/德国/有色/豆粕”不完全一致。映射已落 `config/global_rotation_assets.json`，13 项全部标 `unverified`，未伪造供应商代码 | `config/global_rotation_assets.json`；本文第 9 节 |

## 4. 硬编码、绝对路径与异常吞掉清单

### 4.1 硬编码日期与阈值

| 位置 | 内容 | 风险 |
| --- | --- | --- |
| `factors/opportunities/scan.py` | `period < '2026-07-01'`（多处） | 固定日期切窗，跨期后语义漂移 |
| `scan.py` | 财务覆盖 ≥4000、quality 覆盖 ≥1000 | 固定股票覆盖阈值，小样本或扩容后误判 |
| `scan.py` | `EXT_EFF_MIN = 5.0`、`AUCTION_MAX_AGE_DAYS = 60` | 外部因子有效性与竞价时效写死 |
| `scan.py` | `EXT_POOL_DIR = Path(r"data/factorpool/output/daily_scores")` | 外部因子池缺失时无替代说明 |
| `data/traffic_light.py` | `_ensure_parquet()` 缺文件即联网拉 baostock | 只读页面链路可能触发外网 |
| `factors/policy/timing_system.py` | 各维度缺数据回退中性 50 | 缺输入也能产出分数，掩盖 blocked |
| `deck/live_api.py` | 顶层 `ok: true` 覆盖子模块失败；大量 `except Exception: pass` | 失败被吞掉后仍表现为成功响应 |
| `deck/system_live.py` | `schtasks`/`netstat` 仅 Windows；查询失败返回空数组 | 无法区分未配置、查询失败、已禁用 |
| `ui_v2/pages/portal.html` | `data_semantic` 与 title 硬编码“每日 18:30 收盘后由管道更新” | 无调度证据的确定承诺 |

### 4.2 绝对/反斜杠路径

- `scan.py`：`BARS_DB = r"data\cache\bars.db"`、`FIN_DB = r"data\cache\finance.db"`（Windows 反斜杠相对路径）。
- `factors/policy/global_rotation.py`：`CACHE = Path(r"data/factorpool/output/cache")`（相对路径，但写死目录）。
- `factors/opportunities/tech_pitch_v3.py`：`BARS_DB = Path(r"data/cache/bars.db")`。
- `deck/system_live.py`：`DBS` 固定五个 `data/cache/*.db`。
- 结论：均为仓库相对路径，不写盘外绝对路径；但写死目录导致不能按 run 隔离（Task 4/5 处理）。

### 4.3 失败吞掉后返回成功

- `live_pools()`：缺文件 → 列表长度 0，顶层 `ok: true`。
- `live_brief()`：各块 `except: pass` → `ok: true, n: 0`。
- `live_chain()`：单环节 `ok: false`，顶层仍 `ok: true`。
- `live_timing_dash()`：无文件仅返回 `ok: true, ts`。
- `live_portal_dash()`：每块 `try/except: pass`，缺块即缺字段。
- `data/daily_pipeline.py`：包含分钟 7z、全市场增量、因子池 scheduler、扫描/Pitch，**本次未运行**，不能作为当前页面数据来源的证明。
- `main.py`：各子命令打印“模块开发中”，不能作为生产入口。

## 5. 主系统数据路径与快照

| 类别 | 路径 | 本机状态 |
| --- | --- | --- |
| 主行情库 | `data/cache/bars.db` | 存在，24,576 B，仅极小样本 |
| 增量库 | `data/cache/bars_incr.db` | 存在，与 `bars.db` SHA256 相同 |
| 股票列表 | `data/cache/stock_list.csv` | 存在，79 B，格式 `000938.SZ` |
| 财务/质量/分钟/市值库 | `data/cache/{finance,finance_quality,minute,hist_mv}.db` | 缺失 |
| 演示库 | `data/demo/`（`build_demo_db.py`、`demo_stock_basic.csv`） | 存在；`demo_bars.db` **缺失** |
| 六股真实快照 | `data/real-smoke/sample` | **缺失**（被 `.gitignore`，仅 Windows 上有验收记录） |
| 分析产物 | `logs/`、`output/`、`report/` | 缺失 |
| 外部因子池 | `data/factorpool/` | 缺失 |
| 私有配置 | `config/params.yaml`、`config/etf_pool.yaml` | 缺失（仅 `.example`） |
| 私有配置 | `harness/home/settings.yaml` | 存在，233 B（仅记录哈希，未读取正文） |

## 6. 关键文件 SHA256（本机实测）

| SHA256 | 字节 | 相对路径 |
| --- | --- | --- |
| `6afae2f07b878510de716053fc702b265ee61f379fd1b5c25488938b81a5a4a2` | 388 | `config/data_sources.json` |
| `195c03b079b36f3e2883d3dcb632598251c34163950c160de3b03eb60cf94620` | 764 | `config/real_data_sample.json` |
| `f5f87b94b3148fa3b1d6293a41b8a29f372f44276d5063d085b88fcf6b425aae` | 514 | `config/real_watchlist.json` |
| `791030578f3b058a38574e8a7ea5f1fbf3c5de1b6abd9c63a30e516674b3fed2` | 1437 | `config/navigation.json` |
| `ed243029ad86e46c1923eab393bb3b1615c8521796e68f1c5162745feafb32dd` | 17646 | `config/params.yaml.example` |
| `f711ec285a8dc904f64c22e6cac8f07d1dbcd8ed8d0d6f332cec2bce1e739648` | 3172 | `config/etf_pool.yaml.example` |
| `8d12cdf50d86f3623cc21b75d635ab3f508c8b5b03e1a80e74625d43105caf2d` | 896 | `config/strategies.yaml.example` |
| `7a2e529ddb63db86a0ab653f028aee6d8906205069f55b56c30428924b12b767` | 116 | `config/web_security.yaml.example` |
| `1d571045d7dcb884d2243f3b517fa408d1856b3e962f08c05a5656fe281dd9ca` | 233 | `harness/home/settings.yaml`（仅哈希） |
| `296eeed7aa93424a21fffcca3f818afc923d76907c760ed26470d6591fa839d6` | 3598 | `data/demo/build_demo_db.py` |
| `0567d8968a02f72feef142952986873b041e837702e4fb5d2de87a01e9f6f0a8` | 670 | `data/demo/demo_stock_basic.csv` |
| `6133b43db79268883b3d7afe3044071b98b72c92ec067094fba0807a86ac2c7d` | 24576 | `data/cache/bars.db` |
| `6133b43db79268883b3d7afe3044071b98b72c92ec067094fba0807a86ac2c7d` | 24576 | `data/cache/bars_incr.db` |
| `5f59396d530c7382afa55501bd3eef5b0ebe5e4f3e379573909c2aaab0427d9f` | 79 | `data/cache/stock_list.csv` |

说明：`bars.db` 与 `bars_incr.db` 哈希相同，说明增量库尚未独立积累；`settings.yaml` 仅记录哈希，未纳入任何输出内容。

## 7. 本机无法核对项

| 项目 | 原因 | 处理 |
| --- | --- | --- |
| Windows 生产服务 PID | 服务运行在 100.123.203.13，本机 8787 被静态 `http.server` 占用 | 标注“本机未验证”，Task 7 浏览器验收时补证据 |
| 六股快照 SHA256 | `data/real-smoke/` 被 `.gitignore`，仅 Windows 有 | 标注“本机缺失”，沿用 `docs/HANDOFF.md` 的验收记录 |
| `config/params.yaml`、`config/etf_pool.yaml` | 私有配置仅 Windows 有 | 不创建、不覆盖，只记录缺失 |
| Windows 目录权限 | 本机无法验证 jack 用户对缓存/产物的读写 | 标注“未验证”，Task 7 补 |
| `schtasks` 实际任务清单 | WSL 无 `schtasks` | 标注“unknown”，页面不得断言“无任务” |
| pyarrow 安装可行性 | 本机 Python 3.9.6 隔离 venv 实测 pyarrow 21.0.0 + pandas 2.3.3 可读写合成 Parquet；WSL 生产环境仍未安装、未验证 | 已在 Task 3 记录实际版本，生产安装需另行授权（见第 9 节） |

## 8. 各模块当前可用性判定（供 Task 2 使用）

| 模块 | 本机判定 | 依据 | 目标状态语义 |
| --- | --- | --- | --- |
| 择时 | missing | `output/timing_system*.json` 缺失 | missing（若计算但输入不足 → blocked） |
| 择时趋势 | missing | `output/traffic_light.json` 缺失 | missing；缺 `state` 时页面结束加载 |
| 五福轮动 | blocked | 无 Parquet 引擎、无 `data/factorpool/` | blocked（原因：引擎/文件/覆盖） |
| 跨资产防守 | blocked | 同上 | blocked，隐藏不能等于“正常” |
| 机会池/Pitch/远期池/止损 | missing | `logs/` 缺失 | missing；有效空结果才 empty |
| 今日要点 | missing | 上游产物缺失 | missing；部分缺失需说明 |
| 实时行情 | unknown | 未联网，不触发 | unknown/error，不显示 0 |
| 数据源健康 | missing+stale 混判 | `_api_health()` 逻辑 | 拆 missing/stale/invalid |
| 计划任务 | unknown | 非 Windows | unknown，不返回空数组 |
| 决策链 | missing（多环节） | 13 环节产物缺失 | 逐环节状态，顶层不得掩盖 |

**结论：** 当前本机不具备“计算即可恢复”的条件。缺目录只能说明文件未生成，不代表执行一次 mkdir 或安装引擎就能得到有效业务数据；五福轮动还需四指数/九 ETF 的实际 Parquet、列、覆盖与日期校验。以上均留待 Task 2（状态契约）与 Task 3（五福输入）处理，生产切换和定时任务不在本次范围。

## 9. Task 3 补充：Parquet 依赖与五福轮动就绪条件

### 9.1 引擎与版本

- `requirements.txt` 新增 `pyarrow>=15`，保留“pyarrow 或 fastparquet 只需一个可用”的约定；未同时安装 fastparquet。
- 隔离验证（不触碰仓库环境与生产）：

```bash
python3 -m venv --system-site-packages /tmp/gr-parquet-venv
/tmp/gr-parquet-venv/bin/python -m pip install pyarrow
/tmp/gr-parquet-venv/bin/python -c "import pyarrow,pandas,numpy,sys;print(sys.version.split()[0],pandas.__version__,numpy.__version__,pyarrow.__version__)"
# 3.9.6 2.3.3 2.0.2 21.0.0
```

- 实际安装版本：**pyarrow 21.0.0**（Python 3.9.6 / pandas 2.3.3 / numpy 2.0.2，macOS 临时 venv）。
- 用合成数据写入真实 Parquet 再读取：4 指数按列名、9 ETF 模拟 GBK 乱码列名按位置映射；`widget()` 返回 `date=2026-10-23`、9 项资产，`compute()` 输出 JSON 不含 `NaN/Infinity`。
- 未在 Windows WSL 生产 `.venv` 安装或验证；不以“`import pyarrow` 成功”代替指数/ETF 数据验收。

### 9.2 输入就绪条件（`factors/policy/global_rotation.py`）

| reason | state | 触发条件 |
| --- | --- | --- |
| `engine_unavailable` | blocked | 无 pyarrow/fastparquet |
| `input_missing` | blocked | `wufu_idx.parquet` / `wufu_etf.parquet` 不存在 |
| `config_missing` / `config_invalid` | blocked | 映射配置缺失或结构/数量不符（要求 4 指数 + 9 ETF） |
| `column_missing` | blocked | 配置声明的显式列名不在缓存中 |
| `coverage_insufficient` | blocked | 按位置映射的列数不足 |
| `asset_unsupported` | blocked | 配置标 `unsupported`，禁止用替代资产静默顶替 |
| `history_insufficient` | blocked | 指数有效点 <11 或 ETF 有效点 <61 |
| `input_stale` | blocked | 输入最新日期落后业务日 >8 天 |
| `input_unreadable` / `input_invalid` | error | 文件不可解析、索引非日期、面板为空、最新指数行存在空值 |
| `price_non_positive` | error | 存在 0、负值、Inf 或 NaN 污染的价格 |

- 校验全部发生在计算与写盘之前；失败时不生成 `output/global_rotation.json`，也不覆盖上次成功产物。
- 写盘使用 `json.dumps(..., allow_nan=False)`，非有限数值在摆件接口中被过滤为 `null`。
- 摆件按配置顺序读取，展示仍按动量降序（与旧页面行为一致）。

### 9.3 资产映射配置

- 新增 `config/global_rotation_assets.json` 与同构 `config/global_rotation_assets.json.example`。
- 每项字段：`key / name / column / column_index / vendor / vendor_symbol / support / permission / alternative / note`；`support ∈ verified/unverified/unsupported`。
- 4 指数沿用旧代码列名（`沪深300`、`中小综指`、`创业板指`、`中证A500`）；9 ETF 因缓存列名为 GBK 乱码，`column=null` 并按 `column_index 0..8` 位置映射。
- 13 项当前全部为 `unverified`：本机无 `data/factorpool/` 缓存，未核对实际列名；`vendor_symbol` 一律留空，未伪造供应商代码；`permission` 记为 `local_read_only`（读取本地缓存）。
- `etf_safe`（避险资产）与 `etf_gold2`（疑似重复黄金）在 note 中标明未确认；替代资产只在 `alternative` 里作人工提示，代码不会自动采用。

### 9.4 接口原因透传

- `deck/live_api.py: live_wufu_rotation()` 优先读取 `RotationInputError.state/reason`，将 `input_missing`、`history_insufficient`、`price_non_positive` 等原因直接暴露到 `module`，不再统一压成 `input_invalid`。

### 9.5 测试证据

实现前先写测试并观察红状态：`Ran 17 tests ... FAILED (failures=2, errors=15)`（缺 `RotationInputError` 与映射配置）。实现后：

```bash
python3 -m unittest discover -s tests -p 'test_global_rotation_inputs.py' -v
# Ran 18 tests，OK (skipped=1：本机无引擎，跳过真实 Parquet 读取)

/tmp/gr-parquet-venv/bin/python -m unittest discover -s tests -p 'test_global_rotation_inputs.py' -v
# Ran 18 tests，OK（含真实 Parquet 读写）

python3 -m unittest discover -s tests -p 'test_portal_status.py'
# Ran 44 tests，OK
node --test tests/portal-status.test.cjs
# tests 10 / pass 10 / fail 0
```

### 9.6 剩余阻塞

- 未在 WSL 生产 `.venv` 安装 pyarrow 或复跑测试；生产依赖安装需另行授权。
- 本机无 `data/factorpool/output/cache/*.parquet`，映射仍为 `unverified`；真实列名、ETF 品种与覆盖需 Task 4 用有界采集/真实快照复核。
- 未切换生产数据源、未启用定时任务、未运行旧全量流水线、未拉取真实供应商数据。
