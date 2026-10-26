# 首页真实数据接入与空状态治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Trae 未安装该技能时，按本文逐项执行、记录证据；不得把未勾选项视为完成。

**Goal:** 让门户首页明确展示各模块的数据模式、实际数据日期、覆盖范围和失败原因，分阶段接入真实数据及分析产物，使“接口能访问”与“业务数据可用”分别验收。

**Architecture:** 保留演示库和六股真实快照，用独立运行目录构建有来源、覆盖和版本信息的分析产物；门户只读同一批已验收产物，通过 API 展示。先修正缺失/陈旧状态，再按依赖顺序接数据、计算及调度，不直接运行旧全量流水线填充页面。

**Tech Stack:** Python、SQLite、pandas、Parquet（pyarrow）、现有 HTTP API、原生 JavaScript、WSL Ubuntu / systemd user services。

## Global Constraints

- 这是交给 Trae 的待实施方案。本次仅交付文档，不表示已接入首页、不批准立即切换生产或启动全市场采集。
- 项目：huiyuanaisherry/deepseek-harness-quant；所有需求、进度、证据索引放仓库 docs，禁止依赖 Mac 外部知识库。
- 目标 Windows LAPTOP-9QL895HA / 100.123.203.13，WSL Ubuntu 用户 jack，项目 /home/jack/apps/deepseek-harness-quant，服务 .venv/bin/python。
- 生产基线文档提交 a7b6022，上一轮功能提交 8198b06；开始时重新核对 HEAD、工作区及服务状态，用户后续修改优先保留。
- 保留 data/demo、data/real-smoke/sample、config/params.yaml、harness/home/settings.yaml，以及其他本地未提交文件；真实数据、Token、模型 Key、管理令牌和 Cookie 不进入 Git、截图、普通日志或文档。
- 复用已有 Tushare Pro 兼容客户端和网页保存的官方/HTTP/HTTPS 中转配置；不得恢复硬编码供应商地址、绕过目的地检查或输出 Token。
- 不自动交易，不调用模型生成选股结果，不用六只股票计算“全市场”分位/宽度/拥挤度，不伪造财务值、评分、历史或成功状态。
- 新增动态业务配置提供 .example 模板；前端通过 API 读取，不硬编码股票、ETF 池、日期和状态。
- 生产切换、扩大采集范围、启用定时任务分别提供具体可审查的范围、请求预算、回滚方案，再由用户确认执行；之前的小样本授权不等于这些操作的授权。

## 一、背景及已确认问题（2026-10-26）

用户访问的是根路径 / 门户，不是 /real-watchlist。首页显示“主系统：演示数据”和数据日 2026-05-15；真实观察池独立读取六股快照，最近实际交易日为 2026-10-23。观察池技术验收通过不等于完整策略验收，strategy_acceptance 仍为 false。

只读核查 Windows HEAD=a7b6022；logs、output 目录不存在；pyarrow、fastparquet 均未安装。以下是源码依据与实施入口：

| 模块 | 当前读取逻辑 / 文件 | 问题与目标 |
| --- | --- | --- |
| 首页聚合 | deck/live_api.py: live_portal_dash / live_timing_dash | 择时读取 output/timing_system_*.json；缺失不能继续表现成正常响应下的空白 |
| 择时趋势 | output/traffic_light.json；ui_v2/pages/portal.html 的 tl.state 条件 | 没有结果时没有结束“加载中”；应明确缺失原因与前置条件 |
| 机会/Pitch/远期池 | deck/live_api.py: live_pools；logs/opp_pool_*.json、pitch_v2_*.json、tech_pitch_*.json、pitch_track_pool_*.json | 缺文件被默认空列表转换为 0；应区分未计算和有效零结果 |
| 今日要点 | deck/live_api.py: live_brief | 由多个分析结果聚合；没有要点不能代表已完成全部分析，也不等同只缺一个 daily_report 文件 |
| 五福轮动 | factors/policy/global_rotation.py；data/factorpool/output/cache/wufu_idx.parquet、wufu_etf.parquet | 缺 Parquet 引擎；安装依赖后仍需检查文件、列、资产覆盖及日期，不能保证自动恢复 |
| 数据源健康 | deck/system_live.py: _api_health | 11 项检查缺失或文件年龄；目前缺失也统称“滞后”，需拆分缺失、过期和损坏 |
| 计划任务 | deck/system_live.py: _next_schedule | 调用 schtasks 并解析中文输出；WSL 不兼容/查询失败也会返回空列表，不能直接断言无任务 |
| 旧日更链 | data/daily_pipeline.py | 包含分钟 7z、全市场增量、外部因子池与扫描；路径/配置/退出码语义需先审查，禁止直接一键运行 |

网页“33/36 在线”测的是接口可达；“11 项滞后”是文件健康，两种指标不是同一件事。页面固定写“18:30 更新”不构成真实调度证据。

## 二、实施顺序及交付范围

第一里程碑：Task 1–3，页面诚实显示状态，依赖可诊断，不切换数据源。
第二里程碑：Task 4–5，独立目录中的真实基础数据与可计算模块，浏览器验证，不宣称全市场选股完成。
第三里程碑：Task 6–7，完整分析链验收后，单独审批切换和调度。

### Task 1：建立依赖清单与只读基线

**Files:** 新建 docs/reviews/2026-10-26-portal-data-dependency-review.md；检查 deck/live_api.py、deck/system_live.py、data/daily_pipeline.py、data/cache.py、data/real_data_sample.py、factors/policy/timing_system.py、data/traffic_light.py、factors/policy/global_rotation.py、factors/opportunities/scan.py、pitch_v2.py、tech_pitch_v3.py。

- [ ] 阅读 docs/README.md、requirements/real-data-validation.md 和 HANDOFF.md 最新记录；核对工作区、提交及两项服务，不覆盖私有配置。
- [ ] 为每个首页模块记录“原始数据→计算入口→输出路径→读取函数→页面字段”；分别记录实际存在、缺少、权限不足、不可运行的依赖。
- [ ] 核实代码格式（000938.SZ 等）、复权基准、单位、财务披露时间、指数/ETF 最小历史长度；窗口由算法实际需要推导，不凭经验统一取 25 天。
- [ ] 检查全链硬编码日期、绝对路径、外部因子池缺失、固定股票覆盖阈值、失败吞掉后返回成功等行为；旧 main.py screen 骨架不能用作生产入口。
- [ ] 记录主系统数据路径、快照路径、关键配置及数据文件 SHA256、当前服务 PID。报告仅存相对路径、日期、数量和脱敏状态。

**验收：** 每个页面模块都有可追溯依赖表；不通过运行旧流水线来探测副作用。不把目录不存在解释为所有功能只需 mkdir 即可恢复。

### Task 2：统一模块可用性契约，修复误导性空状态

**Files:** 新建 deck/portal_status.py、tests/test_portal_status.py、tests/portal-status.test.cjs；修改 deck/live_api.py、deck/system_live.py、ui_v2/pages/portal.html，检查 ui_v2/components/sidebar.js 的全站模式提示，顶栏沿实际页面加载调用链调整。

**Interfaces:** 新模块提供纯函数 build_module_status(*, state, mode, data_date, generated_at, scope, reason, run_id) -> dict；调用方负责从真实文件与运行记录确定这些值。首页聚合新增 modules 映射，保留原字段兼容其他页面。

```json
{"modules":{"opp_pool":{"state":"missing","mode":"demo","data_date":null,"generated_at":null,"scope":"unknown","reason":"artifact_missing","run_id":null}}}
```

state 仅允许 ready / empty / missing / stale / blocked / error；mode 为 demo / real / unknown。empty 仅用于经过校验且 items 为空的有效产物；missing 表示文件未生成；blocked 表示缺少计算前置条件。处理中由独立运行状态表达，不覆盖最后一次成功结果。API 禁止返回绝对私有路径或原始含凭据异常。

- [ ] 先添加失败测试：文件缺失时数量为 null、state=missing；有效空结果数量 0、state=empty；JSON 损坏为 error；权限/覆盖不足为 blocked；陈旧有效结果为 stale 并保留原数据日。
- [ ] 实现状态构建与各模块适配，不把顶层 ok=true 当所有子模块成功。首页 GET 只读，不触发供应商查询、模型调用、数据生成或目录写入。
- [ ] 前端为上述六种状态提供确定文案；missing/blocked/error 不展示绿色“正常”或业务数字 0；旧 API 暂无 modules 时显示“状态未知”，保持兼容。
- [ ] 择时趋势成功但缺 tl.state、请求失败、请求超时都结束“加载中”；每个卡片独立显示失败，不让一项失败清空全页。
- [ ] 区分“接口可达”“数据可用”“最近成功计算”；删去无调度证据时“每日 18:30 自动更新”的确定承诺。
- [ ] 将 11 项健康统计区分缺失、陈旧、损坏，保留原始兼容字段但按业务数据日判断可用性；不能 touch 文件就恢复新鲜。

**验证命令：** `.venv/bin/python -m unittest discover -s tests -p 'test_portal_status.py' -v`；`node --test tests/portal-status.test.cjs`。先观察指定用例失败，再实现并确认通过。测试使用临时合成文件，禁止访问真实供应商。

### Task 3：明确 Parquet 依赖与五福轮动就绪条件

**Files:** 修改 requirements.txt、factors/policy/global_rotation.py；新建 tests/test_global_rotation_inputs.py；扩展 Task 1 依赖报告。

- [ ] 添加合成测试：缺引擎、缺文件、缺列、日期落后、历史不足、非正价格及覆盖不足分别给出 blocked/error；完整样本可计算，数值不含 NaN/Infinity。
- [ ] 将 pyarrow 加入明确依赖，按 Windows WSL 现有 Python/pandas 版本验证兼容性并记录实际安装版本。只需一个可用引擎，不必同时安装 fastparquet。
- [ ] 在隔离环境验证读取合成 Parquet；不要用“import pyarrow 成功”代替 ETF 与指数数据验收。
- [ ] 为四指数、九 ETF 的真实映射建立配置与 .example，逐项记录供应商是否支持、权限和替代差异。替代资产不得静默冒充原资产；不支持时保持 blocked。

**验证命令：** `.venv/bin/python -m unittest discover -s tests -p 'test_global_rotation_inputs.py' -v`。本任务不授权在生产安装或拉取真实数据。

### Task 4：独立真实数据运行目录和有界采集

**Files:** 新建 config/portal_data.json.example、data/portal_pipeline.py、tests/test_portal_pipeline.py；复用 data/pro_client.py、data/real_data_sample.py 及现有配置服务，按实际读取调用关系调整。

**Interfaces:** 新入口 `python -m data.portal_pipeline --config <path> --plan` 只打印脱敏的接口/资产/窗口/预计请求上限，不联网；`--collect` 仅处理显式配置范围；`--compute` 只读本地原始数据；`--validate` 只读检查完整性。一次只指定一个动作，否则退出非零。

- [ ] 配置明确 universe、indices、etfs、start_date、end_date、max_requests、timeout_seconds、output_root，拒绝隐式 all；实际配置默认禁用采集/调度，并提供 .example。
- [ ] 使用新目录 data/real-portal/runs/<run_id>/；禁止覆盖六股已验收快照和演示库。所有输出日期、资产范围与复权基准写入 manifest.json。
- [ ] 先以合成客户端测试请求预算、超时、分页上限、失败退出、重跑去重、配置变化隔离及未授权目的地拒绝。生产请求复用现有网页配置，不自行通过 SDK 私有属性更换地址。
- [ ] 先交付脱敏 --plan 给用户确认实际新增资产、接口权限和请求量，再执行有界采集；没有授权或供应商权限就记录 blocked，继续其他独立模块。
- [ ] 按现有验证规则校验交易日历、停牌证据、单位、重复键、none/qfq、基本信息、财务披露日；指数/ETF 单独校验，财务未知不补零。
- [ ] 输出 verification.json：每项检查、实际日期、覆盖率、失败原因；请求失败不推进成功日期、不清空上次成功数据。

**验证命令：** `.venv/bin/python -m unittest discover -s tests -p 'test_portal_pipeline.py' -v`；`.venv/bin/python -m data.portal_pipeline --config config/portal_data.json.example --plan`（预期无联网、无数据目录写入、无秘密输出）。

### Task 5：依赖分级计算与同批产物发布

**Files:** 修改 data/portal_pipeline.py、data/traffic_light.py、factors/policy/timing_system.py、factors/policy/global_rotation.py、deck/live_api.py；新建 tests/test_portal_artifacts.py。

- [ ] 先实现可独立验证的指数趋势；现有择时四维评分、情绪、宽度、拥挤度按各自完整依赖分别计算。缺全市场覆盖时不得把六股结果标记“市场”。
- [ ] 每个计算器显式接收输入目录、输出目录、as_of；禁止读取演示目录、旧全局 logs/output 或静默替代成最新日期。旧读取路径只保留为明确 demo 模式。
- [ ] 同一 run_id 产物包含 schema_version、mode、scope、data_date、generated_at、input_revision 和模块状态；保留原消费字段，新增元数据不破坏旧页面。
- [ ] manifest 记录每个产物的 SHA256 和覆盖；文件写到临时位置后原子替换。发布 current.json 指针前校验必需产物；聚合请求固定读取一个 run_id，禁止混批。
- [ ] 失败保留上次成功批次并标 stale/最新运行失败；禁止将旧数据标今天、借用演示结果补真实模块。部分模块 blocked 时明确展示，不能把整个链标为完整通过。
- [ ] 测试半写入、坏 JSON、错误哈希、日期错位、指针变化、旧批次与新批次混合时拒绝发布或重试有限次数；API 读请求不创建 WAL/SHM 或改写数据。

**验证命令：** `.venv/bin/python -m unittest discover -s tests -p 'test_portal_artifacts.py' -v`。首次真实计算仅在 Task 4 已批准范围内离线执行。

### Task 6：选股/Pitch/简报链单独验收

**Files:** 根据 Task 1 映射修改 factors/opportunities/scan.py、pitch_v2.py、tech_pitch_v3.py、deck/live_api.py；新增 tests/test_portal_strategy_readiness.py。

- [ ] 先处理已记录的策略阻塞：历史 ST/可交易状态、按披露日可知的财务三表与累计转单季、完整目标股票池的估值分位、实际外部因子覆盖。每项写明覆盖和检查结果。
- [ ] 未满足条件时模块 blocked，不允许通过降低阈值、关闭规则、编造因子或价格排序兜底来“产生股票”。六股只可标观察池内技术筛选，不能叫全市场机会池。
- [ ] 扫描和 Pitch 复用既有策略，不建立新的推荐逻辑；有效零结果只有在输入完整、计算成功及产物验收通过时才展示 0。
- [ ] 简报说明哪些模块已分析、哪些未就绪。未导入真实持仓时持仓模块显示“未配置持仓”，不生成持仓或止损记录。
- [ ] 测试缺财务、缺市场分位、历史 ST 未知时拒绝策略验收；有效全条件合成输入才允许 ready/empty。

**验证命令：** `.venv/bin/python -m unittest discover -s tests -p 'test_portal_strategy_readiness.py' -v`。只有扩大采集范围获批后才验证真实目标池；无法完成的模块列为剩余阻塞，不掩饰。

### Task 7：WSL 调度、生产切换与浏览器验收

**Files:** 新建 deploy/systemd/deepseek-portal-data.service.example、deepseek-portal-data.timer.example；修改 deck/system_live.py；新建 tests/test_portal_schedule.py；更新 docs/HANDOFF.md、requirements/real-data-validation.md、docs/README.md。

- [ ] 统一运行状态文件：任务 enabled、运行中/成功/失败、last_attempt、last_success、next_run、run_id。明确运行时区 Asia/Shanghai；交易日来自已校验日历，非交易日记录跳过原因。
- [ ] WSL 选用 systemd user timer；Windows schtasks 只用于明确的 Windows 后端，查询失败显示 unknown/error，禁用显示 disabled，无任务显示 unconfigured，禁止全返回空数组。
- [ ] 计算进程设置可靠互斥、总超时、请求预算、重试上限和失败退出；验证服务单实例，失败不修改最后成功指针。不能只检查 returncode=0，必须校验产物。
- [ ] 提供 timer 模板和只读检查命令，但默认不 enable/start。提交具体采集预算、触发时间、失败恢复方式及目标目录供用户批准后再安装启用。
- [ ] 生产切换前列出所有读路径：DailyCache、门户聚合、顶栏、健康检查和分析产物。统一真实来源或显式分模块标注；仅改 LWQUANT_CACHE_DIR 不构成完整切换。
- [ ] 先在隔离端口使用合成数据验证全状态，再在用户批准后部署真实批次。备份服务覆盖项/当前指针，回滚只恢复配置与指针，不删除真实采集文件，不碰模型配置。
- [ ] 在 Mac Chrome 访问 http://100.123.203.13:8787/ 验证登录、刷新、各卡片来源/日期/范围、有效零结果和失败提示、观察池仍可用。无成功浏览器证据时明确标未验收，不能用 curl 200 替代。

**验证命令：** `.venv/bin/python -m unittest discover -s tests -p 'test_portal_schedule.py' -v`；`.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`；`node --test tests/*.test.cjs`。systemd 安装后以 `systemctl --user list-timers --all` 和 `systemctl --user status deepseek-portal-data.timer` 核对，不用描述性文案代替证据。

## 三、最终验收清单（每阶段分别报告）

- [ ] 所有卡片结束加载；每项空状态有原因，文件缺失不再显示业务 0。
- [ ] 首页、顶栏、数据健康显示一致的数据模式和实际交易日；真实观察池与市场范围明确区分。
- [ ] API 可达、业务数据可用、计算/调度成功分别展示；缺失/陈旧/错误不再混称在线。
- [ ] 依赖安装和真实数据齐备分别验收；五福轮动资产映射与算法窗口有证据。
- [ ] 无网络/权限不足/过期/输入缺失时保留旧批次和日期，并展示真实失败状态。
- [ ] 全链 HTTP GET 不采集、不调用模型、不改数据；计算结果不混批。
- [ ] 真实数据不入 Git；私有配置和受保护目录哈希对照无意外变化。
- [ ] 生产切换及 timer 启用均有单独用户授权、实际运行证据和回滚步骤。
- [ ] 每个 task 一次独立提交；交付提交号、实际测试命令/结果、Windows 服务验证、浏览器证据和未完成阻塞。不以“页面已部署”总结“选股系统全部可用”。

## 四、可直接发给 Trae 的任务说明

请先阅读 docs/README.md、docs/requirements/real-data-validation.md 以及本方案。先做 Task 1–3：梳理门户依赖、修复缺失与零结果混淆、定位五福轮动依赖及 WSL 调度状态。按阶段提交代码与测试证据，再推进独立真实目录中的采集/计算。不要直接运行 data/daily_pipeline.py，不要修改已配置的 Token/模型 Key，不要覆盖演示库和六股快照，不要自动扩大到全市场或启用计划任务。任何当前不可计算的模块明确显示阻塞原因，不用模拟数据填满首页。生产切换前提供具体变更与回滚清单供用户确认。所有记录保存在项目 docs，保持换电脑后可继续接手。
