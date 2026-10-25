# 小样本真实数据接入 Implementation Plan

> **For agentic workers:** Use subagent-driven-development; tasks are independent until server validation.

**Goal:** 六只用户授权样本在独立目录完成可重复的真实采集与质量校验，并识别现有策略接入限制。

**Architecture:** 复用 deck.data_settings 的固定 IP HTTP transport 为 Tushare SDK 配置只读 query 适配。新增配置驱动的有限样本 runner，通过 DailyCache 显式绝对路径落库，写入本地验收报告；不改生产数据源。

**Tech Stack:** Python、unittest、pandas、SQLite、现有 Tushare Pro JSON。

**Execution status:** 本轮三项执行任务已完成，实际生产代码为 `a439c87`。Task3 交付是离线技术因子与完整策略的接入差距报告，不代表完整选股/日报通过。结果与下一阶段见 `docs/requirements/real-data-validation.md`。

## Global Constraints

- 不输出 Token，不上传行情，保留演示库和用户模型配置。
- 样本列表、日期长度和阈值位于 config JSON 并有 .example；不在页面/代码写死股票。
- 先测试失败再实现；对改动做独立审查，服务器运行真实样本并检查演示库保持不变。
- 沿用当前用户 fork 工作分支和 PR1，不合并 master，不创建 Mac 知识库。

### Task 1: 统一 Pro 传输

Files: data/pro_client.py, data/fetcher_tushare.py, tests/test_pro_client.py, tests/test_data_settings.py。

- [x] 写测试：完整 URL 原路径不追加 API 名；传递标准 api_name/token/params/fields；客户端配置变更重建；HTTP 未确认拒绝；错误不含上游消息或 Token。
- [x] 运行 `python3 -m unittest discover -s tests -p 'test_pro_client.py' -v` 看到缺失实现。
- [x] 实现 ProClient.query(api_name, fields='', **kwargs) 返回 DataFrame，__getattr__ 提供 SDK 风格的动态 API 调用；复用 resolve_endpoint、PinnedTransport 的限制，不使用环境代理或跟随重定向。fetcher 保留配置缓存，缓存键加入 HTTP 确认。
- [x] 运行新增与现有配置测试，确保客户端热更新、完整路径和安全错误通过。

### Task 2: 配置驱动的独立落库与校验

Files: config/real_data_sample.json, .example, data/real_data_sample.py, tests/test_real_data_sample.py, .gitignore。

- [x] 测试使用合成 DataFrame 与临时目录：重复/负价格/缺失因子/不合法披露日期拒绝；qfq=raw*factor/factor_last；两次相同写入无重复且不改其他库。
- [x] `python -m data.real_data_sample --config config/real_data_sample.json` 串行请求至多 10 只股票。输出目录限制在 data/real-smoke 内，CLI 支持固定 --as-of 便于复现。保存查询结果 CSV 与 bars.db，none/qfq 两种口径；保留原始 Tushare 单位供 normalize_units 统一处理。
- [x] 请求 trade_cal 一次，其余每只 stock_basic/daily/adj_factor/daily_basic/fina_indicator；数据严格上限、字段校验和不完整截断检测。拒绝缺失交易日和最新日不一致，财务同时约束 end_date 和 ann_date 不晚于 as-of。
- [x] 使用 DailyCache 显式绝对路径写入两次并读回比对，写 verification.json（通过与失败、行数、日期、范围、demo_unchanged），不打印原始错误或凭据。

### Task 3: Windows 验收与策略接入检查

- [x] 审查 Task1/2 并修正重要问题，运行全部 Python/Node 回归，提交推送既有 PR。
- [x] 通过 SSH 验证目标，传 Git bundle 快进；保留 params.yaml、模型配置和 data/demo，实际运行有限样本任务。
- [x] 记录供应商真实返回日期而非假定当天有行情，检查 SQLite 数据可读、复权及幂等、演示库哈希一致。
- [x] 从六只独立数据构建现有 compute_factors / triggers 的离线验收，无法安全复用的筛选/日报明确写阻塞和下一步，不伪造全市场分位或已有策略收益。
- [x] 将实际提交、报告位置和限制补入 docs/requirements/real-data-validation.md 与 docs/HANDOFF.md，Windows 同步记录。
