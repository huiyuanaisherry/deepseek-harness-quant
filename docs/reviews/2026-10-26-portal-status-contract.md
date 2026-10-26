# 门户模块可用性契约与空状态修复（Task 2 交付记录）

> 对应计划：`docs/superpowers/plans/2026-10-26-portal-real-data-for-trae.md` Task 2。
> 本记录只覆盖“状态诚实化”，不切换数据源、不生成业务数据、不启用调度。
> 路径使用仓库相对路径；不含 Token、Cookie、模型 Key、私有配置正文和绝对私有路径。

## 1. 交付范围

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| 新增 | `deck/portal_status.py` | 六态契约、产物评估、数据模式解析（只读纯函数） |
| 新增 | `ui_v2/core/portal_status.js` | 前端状态文案与数值展示判定（`window.LW.portalStatus`） |
| 新增 | `tests/test_portal_status.py` | Python 契约与聚合测试（临时合成文件） |
| 新增 | `tests/portal-status.test.cjs` | Node 前端契约测试 |
| 修改 | `deck/live_api.py` | `live_portal_dash` 新增 `data_mode` 与 `modules`；`live_wufu_rotation` 新增 `module` |
| 修改 | `deck/system_live.py` | `_api_health` 区分缺失/陈旧/损坏；新增 `_next_schedule_detail` |
| 修改 | `ui_v2/pages/portal.html` | 六态文案、逐卡失败、KPI 数值守卫、去掉 18:30 承诺 |
| 修改 | `ui_v2/components/statusbar.js` | 顶栏不再假设固定更新时间；失败显式“状态未知” |
| 修改 | `ui_v2/components/sidebar.js` | 仅在本页加载 `portal_status.js` 时启用状态判断，其余页面保持原数值渲染 |

保留未动：`data/demo`、`data/real-smoke/sample`、`config/params.yaml`、`harness/home/settings.yaml`，以及所有私有配置。

## 2. 契约

### 2.1 后端 `deck/portal_status.py`

- `build_module_status(*, state, mode, data_date, generated_at, scope, reason, run_id) -> dict`
- `state` 仅允许 `ready / empty / missing / stale / blocked / error`；`mode` 仅允许 `demo / real / unknown`。
- `empty` 只用于“文件存在、结构有效、items 为空”的有效产物；`missing` 表示未生成；`blocked` 表示缺计算前置条件。
- `reason`、`scope`、`run_id` 收敛为短代码（如 `artifact_missing`、`input_invalid`），不返回异常原文或绝对路径。
- `assess_artifact` / `assess_latest` 只读：缺文件 → `missing/artifact_missing`；JSON 损坏 → `error/artifact_corrupt`；列/结构不符 → `error/artifact_schema_mismatch`；超过 `stale_days` → `stale/artifact_stale` 且保留原数据日；`PermissionError` → `blocked/permission_denied`。
- `resolve_mode` 依据主系统缓存目录（`LWQUANT_CACHE_DIR` 或配置）判定 `demo / real / unknown`，配置损坏或缺失返回 `unknown`，不猜测。

### 2.2 聚合接口 `/api/live/portal_dash`

新增字段（旧字段全部保留）：

- `data_mode`：`demo / real / unknown`
- `modules`：12 键 `opp_pool, pitch, tech_pitch, stop_alerts, forward_track, timing, traffic_light, global_rotation, brief, chain, api_health, schedule`

规则：

- 文件型模块按 `logs/`、`output/` 的最新产物判定；`traffic_light.json` 缺 `state` 字段记为 `error/artifact_schema_mismatch`，不再显示为正常。
- `brief`、`chain` 由已聚合子结果推导；`chain` 有节点失败 → `stale/chain_lag`；空节点 → `empty/no_items`。
- `api_health` 按数据源条目状态汇总，优先暴露最严重状态；`data_date` 取各源最新业务数据日。
- `schedule` 来自 `deck.system_live._next_schedule_detail`；非 Windows 直接 `blocked/scheduler_unsupported`，不再返回空列表冒充“无任务”。
- 顶层 `ok=true` 不再被当作所有子模块成功；单模块探针异常记为 `error/status_probe_failed`，不影响其余模块。
- 接口保持只读：不联网、不调用模型、不生成数据、不写目录。

### 2.3 五福轮动 `/api/live/wufu_rotation`

- 缺 Parquet 引擎 → `blocked/engine_unavailable`
- 输入文件缺失 → `blocked/input_missing`
- 列/结构错误 → `blocked/input_invalid`
- 计算异常 → `error/compute_failed`
- 有效空结果 → `empty/no_items`
- 产物数据日超过 8 天 → `stale/artifact_stale`
- 不可用时 `ok=false`，并保留原因码供页面展示。

### 2.4 前端 `ui_v2/core/portal_status.js`

- `STATES / LABELS / TONES / VALUE_STATES`：只有 `ready / empty / stale` 允许展示业务数值；`missing / blocked / error` 显示 `—` 与原因。
- 只有 `ready` 使用绿色“正常”色调；`stale` 使用警示色并标注数据日。
- `requestFailure(err)`：请求失败/超时统一转为确定性文案，结束“加载中”。
- `summarize(modules)`：模块汇总，任一模块 `missing/blocked/error` 时不得声称全部正常。
- 旧接口无 `modules` → `unknown`，页面显示“状态未知”。

### 2.5 页面行为

- 首页聚合请求改为 `strict: true`，请求失败不复用旧缓存，直接进入明确的失败态。
- 择时趋势：成功但缺 `tl.state`、请求失败、请求超时都会结束“加载中”并显示原因/状态。
- 每个卡片独立展示失败原因；单个模块失败不清空整页。
- KPI 五卡（机会池/Pitch/技术 Pitch/远期池/止损预警）在非可用态显示 `—` 与模块原因，不显示业务 `0`。
- 健康统计拆分为 可用/缺失/陈旧/损坏/空文件，并按业务数据日判断，不再用“文件多久没 touch”冒充新鲜。
- 删除无调度证据的“每日 18:30 自动更新”承诺；改为“按业务数据日判断；未配置调度时不会自动更新”。
- `sidebar.js` 被 17 个页面共用，仅 `portal.html` 引入 `portal_status.js`；未引入时保持原有数值渲染，避免其它页面被降级成“状态未知”。

## 3. 测试与证据

环境：本机 macOS，Python 3.9.6（`python3`），Node v24.20.0。计划中的 `.venv/bin/python` 在本机不存在，未在 Windows WSL `.venv` 复跑；本次不使用真实供应商。

```bash
python3 -m unittest discover -s tests -p 'test_portal_status.py' -v
```

结果：`Ran 44 tests ... OK`（覆盖六态、缺文件/空结果/损坏/权限、模式解析、健康统计状态汇总、计划任务平台分支、原因码不泄露路径）。

```bash
node --test tests/portal-status.test.cjs
```

结果：`tests 10 / pass 10 / fail 0`（覆盖 stale 不显示绿色、缺 `state` 结束加载、失败与超时文案、汇总不谎报正常、旧接口 unknown、原因码文案）。

```bash
python3 -m py_compile deck/portal_status.py deck/live_api.py deck/system_live.py
node --check ui_v2/components/sidebar.js
node --check ui_v2/components/statusbar.js
```

结果：均通过。另对 `portal.html` 内联脚本执行 `new Function` 语法校验，`script 0 ok`。

## 4. 未完成与阻塞

- 未在 Windows WSL `.venv` 复跑上述测试；服务端实际返回需在部署后重新核对。
- 未做浏览器验收；没有 `http://100.123.203.13:8787/` 的截图或录屏证据，不声称页面已在生产验证。
- 首页多数模块在本机仍为 `missing`（`logs/`、`output/` 不存在），这是有意保留的诚实状态，待 Task 4–5 生成真实产物后再转为 `ready/empty`。
- 未切换生产数据源，未创建或启用任何定时任务；`schedule` 在 WSL 下预期为 `blocked/scheduler_unsupported`。
- 五福轮动仍受 Parquet 引擎与输入文件缺失限制，Task 3 处理依赖声明与就绪条件后仍可能保持 `blocked`。
