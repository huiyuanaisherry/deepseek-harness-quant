# Trae 实施方案：真实数据观察池与演示数据标识

状态：待实现。用户要求本轮只编写方案，交由 Trae 执行。

## 1. 交付目标

用户应能在 Mac 浏览器访问 Windows 服务，直接查看已采集的紫光股份、浪潮信息等六只股票，明确区分：

- 主系统当前使用演示库。
- 新观察池读取 Windows 上已校验的六只股票真实历史快照。
- 真实行情可查看、技术指标可计算，完整选股、候选池和交易能力尚未验收。

本期交付地址：`http://100.123.203.13:8787/real-watchlist`，继承现有管理登录。

## 2. 开始前必须核对的现状

1. 以部署提交 `c8445e17fb3d0963b4ff01e2173360e6d5448b93` 为本方案事实基线，功能代码为 `a439c87`；后续有更新时先核对 diff，不回退用户工作。
2. 用户 fork：`https://github.com/huiyuanaisherry/deepseek-harness-quant`。沿用已有工作分支 `codex/privacy-provider-settings` 和 PR1，不另建重复 PR，不合并 master。
3. 实际运行目录为 Windows / WSL 的 `/home/jack/apps/deepseek-harness-quant`，服务为 systemd user 的 `deepseek-quant.service`、`deepseek-harness.service`。
4. 当前 Python 服务的 `LWQUANT_CACHE_DIR` 指向 `data/demo`；保留此设置。观察池应显式读取独立快照，不改环境变量、不让其他页面意外读六只样本。
5. 项目知识以 Windows 项目 `docs/` 为准，随 fork 同步。先读 `docs/README.md`、`docs/requirements/real-data-validation.md`、`docs/HANDOFF.md` 文末记录；不要登记到 Mac 外部知识库。
6. 连接信息按用户 AGENTS.md 使用公钥 SSH；操作前校验目标 hostname。不要索取 Windows 密码，不改 Tailscale Shields Up。

当前基线测试：Windows 79 项 Python + 31 项 Node 全通过。本地可选 SDK 测试可能因未安装 Tushare 跳过；Windows 应运行实际安装 SDK 的合成集成测试。

## 3. 输入数据与不可变边界

唯一股票名单来自 `config/real_data_sample.json` 的 symbols，不要把六只列表再次写死在 Python、HTML、JS 或另一份配置中。

真实快照目录取自该文件的 output_dir，目前为 `data/real-smoke/sample`，目录中已有：

| 文件 | 用途 |
| --- | --- |
| `bars.db` | `daily_bar`：none / qfq 两种口径；原始 Tushare 单位 |
| `verification.json` | 每只采集校验、行数、日期、停牌证据、演示库未变等结果 |
| `strategy_readiness.json` | 技术指标及完整策略阻塞原因；strategy_acceptance=false |
| `<code>_stock_basic.csv` | 名称、行业、上市日期等基本信息 |
| `<code>_finance_asof.csv` | 已按披露日期校验、去重的原始财务指标 |
| `<code>_suspend_d.csv` | 存在缺失日时保存的停复牌证据，不是每只都有 |

现有快照最新交易日是 2026-10-23：四只各 484 日，中科曙光、海光信息各 474 日；两种口径合计 5768 条；财务合计 47 条。数字仅作验收对照，页面必须从实际文件计算，禁止硬编码。

本期不做：

- 不下载、刷新、补拉供应商行情；打开页面或 GET 接口不得触发外部 API、MCP、模型或数据采集。
- 不修改 Token、模型默认值、主系统缓存目录或既有数据。
- 不把真实快照写入 data/demo，不复制到公开静态目录，不上传 GitHub。
- 不启动全市场筛选、生产日报、定时更新或交易。
- 不把六只样本分位当全市场分位，不提供买卖评级、概率、胜率、虚构排名或策略通过标记。

## 4. 页面与用户操作

### 4.1 数据来源标识

共享侧栏增加轻量状态提示，所有带该侧栏的业务页面都能看到主系统当前数据模式：

- 演示模式：显示「主系统：演示数据」。
- 观察池页额外显示「此页：真实历史快照 · 小样本观察池」，并显示实际数据截至日。
- 生产模式无法判定：显示「主系统数据模式未知」，不得默认成真实。

来源来自 API，不从页面标题、是否配置 Token、是否有 6 只股票推断。不要把观察池的真实快照标签应用到其他演示页面。

### 4.2 观察池列表

沿用现有深色风格，新增侧栏入口「真实观察池」。列表展示：

- 名称、代码、行业。
- 最新收盘价，列表明确统一为未复权；最新日涨跌幅使用原始 daily 的 pct_chg。
- 最新交易日、覆盖天数、快照校验状态。
- 「查看详情」按钮。

顶部说明「历史快照，非实时行情」「主系统仍为演示数据」「完整选股尚未验收」。提供按名称/代码搜索、选中股票、手动刷新页面数据。不提供“更新行情”或“切换生产数据源”按钮。

首次默认选择 API 返回的第一只有效样本，不在代码写死紫光股份。空列表、加载、失败、无权限等状态明确显示。

### 4.3 股票详情

1. 行情：收盘走势和成交量，可选未复权 / 前复权；图表标题、纵轴与 tooltip 都明确口径。前复权基准为该快照最新因子日，不标成实时前复权。
2. 行情明细表：日期、开高低收、成交量、成交额、涨跌幅、换手率，按日期排序，最多返回配置限制的条数。
3. 财务：报告期、披露日、EPS、ROE、净利润同比、营收同比等已存在原始字段。标题为「供应商原始财务指标」，不能改称单季同比或已验证的策略财务因子。空值显示「暂无」，不能显示 0。
4. 技术指标：仅展示 `strategy_readiness.json` 已输出的指标白名单，不在前端重算策略。动量/波动率等小数比例按字段单位转成百分比；RSI 原本为 0–100，不能重复乘 100。
5. 校验：展示该股票校验是否通过、幂等检查、停牌证据天数，显示完整策略尚缺的条件；中文说明替代内部错误堆栈。

图表优先复用仓库已存在的本地能力；若没有图表组件，使用本地 SVG/Canvas 实现简单走势并保留可访问表格。不要为了展示而加载外部 CDN，也不要新建另一套评分逻辑。走势不跨停牌日伪造交易记录。

## 5. 后端与接口约定

建议新建 `deck/real_watchlist.py`，集中处理只读数据访问和安全 DTO；Handler 仅做登录、分发、响应。函数接口建议为：

```python
class RealWatchlistService:
    def context(self) -> dict: ...
    def list_stocks(self) -> dict: ...
    def stock_detail(self, code: str, adjust: str, expected_revision: str | None = None) -> dict: ...
```

方法可以调整实现形态，但下述行为和 API 契约必须保留。上方为接口定义，不是可直接运行的实现。

### 5.1 GET /api/data-context

受登录保护，轻量返回：

- 主系统数据模式：demo / cache / unknown。复用现有服务端数据模式判断，不回显 Token、整个 params.yaml、服务端绝对路径或供应商地址。
- 观察池模式：real_sample / unavailable。
- 样本范围、最新交易日、校验状态、报告生成时间（从实际文件取，不能使用请求时刻冒充采集时间）。
- 元数据字段携带明确中文标签，侧栏不能因为元数据不可用而白屏。

### 5.2 GET /api/real-watchlist

返回 `ok`、`revision`、`source` 和 `stocks`。

- source 必须区分观察池快照和主系统演示模式，包含历史快照说明和实际截至日。
- stocks 仅来自配置名单，含 code/name/industry/close_unadjusted/pct_chg/latest_date/history_count/verification_status 等安全字段。
- 每只失败应明确标 failed / unavailable；其他有效股票仍可查看。总体不能把部分成功写成全部通过。
- report passed=true 也不能推导 strategy_acceptance=true。

### 5.3 GET /api/real-watchlist/stocks/{code}?adjust=qfq&revision=...

- code 必须同时满足严格股票代码格式和当前配置名单；不允许查询任意数据库中股票或拼接任意文件路径。
- adjust 仅支持 qfq / none。未知口径 400，不存在/不在名单的股票 404。
- 返回相同 revision 的 source、基本信息、按日期升序的 bars、原始财务、技术指标、校验状态和策略阻塞项。
- bars 选取必要列，禁止直接 `SELECT *` 后把整个数据库记录原样发送。最大 1000 点，配置中可收紧。
- 响应中明确 volume 单位股、amount 单位元；使用 `data.cache.normalize_units` 将 source=tushare 的手/千元转换一次，防止漏转或重复转换。行情价格单位元。
- 所有 NaN / Infinity 转成 JSON null；日期为明确的 ISO 日期。字段缺失不能伪装 0 或技术指标通过。
- 财务仅输出白名单，保留原始百分比与 EPS 单位；不从原始年/累计指标臆造季度指标。

### 5.4 失败与一致性

- 快照文件完全不存在：安全的 503 / SAMPLE_UNAVAILABLE；未知股票 404；参数非法 400；元数据与数据窗口冲突返回 409 / SNAPSHOT_CHANGED。
- 个别字段/报告缺失不导致整个服务崩溃，页面明确不可用范围。特别是 readiness 缺失时仍可显示已校验行情，但技术指标不可用、策略未验收。
- 使用配置、报告和数据库状态生成 revision；列表和详情校验相同版本。读取期间快照变化时拒绝混合响应，前端重新获取列表一次；持续变化时显示“快照正在更新，请稍后刷新”。
- SQLite 用只读 URI mode=ro，先检查文件存在，禁止调用 DailyCache 默认构造器建表/建库；可以抽出只读适配器复用现有读取与单位转换。缺文件时不得创建空 bars.db。
- 不使用 immutable=1 假设快照永不变化；设置短 SQLite 锁等待，不能卡住服务。
- 目录须沿用 `private_path` 或等价的严格隔离检查，限制在项目 data/real-smoke 内，并拒绝父目录和目标文件符号链接。
- 不接受任意 path、db、table、endpoint、token 等请求参数。SQL 参数化，列名来自服务端固定白名单。
- GET 只读；本期不新增写 API。所有路由均放在 `_gate()` 之后，私有 API 返回 no-store，未登录不能拿到股票或财务内容。
- 不把整个 verification、readiness、CSV、配置文件或异常 str 原样透传；只投影安全字段。

## 6. 前端请求与状态正确性

所有业务数据通过 `LW.api.get('/api/...')` 获取；页面不能直连数据库或直读原始 CSV/JSON 静态文件。

注意现有 `ui_v2/core/api.js` 有两个已知行为：timeout 选项当前没有真正中止 fetch；失败时可能返回旧缓存。Trae 必须在本次实现中处理，不能只传一个 timeout 数值就称为有超时。

推荐为 `LW.api.get` 增加向后兼容选项：

- `strict: true`：错误不返回旧缓存，观察池接口使用它。
- `bypass: true`：刷新时跳过缓存，但不能绕过 revision 校验。
- 用 AbortController 实现真实超时，并有成功/失败后的计时器清理。
- 不改变其他页面默认缓存/重试策略；相同 URL 的普通去重行为保持。

新增测试后再修改共享 api.js。若选择等价替代方案，必须证明不会把旧股票、旧复权口径或旧快照冒充刷新成功，且仍遵守 LW.api 数据入口。

股票快速切换、口径快速切换时使用请求序号或取消机制：迟到响应不得覆盖当前选择。列表、行情、财务数据的 code/revision 必须一致。401 沿用现有登录跳转；网络失败时给出重试按钮，清楚标识旧内容，禁止保留未标记的“验证通过”。

使用 textContent 等安全渲染，不把名称、行业或供应商字段直接插入 innerHTML。

## 7. 文件修改范围

| 文件 | 责任 |
| --- | --- |
| 新增 `deck/real_watchlist.py` | 只读数据访问、来源判断、revision、安全 DTO |
| 修改 `deck/deck_server.py` | 页面和三个 GET 接口，保持鉴权 |
| 新增 `config/real_watchlist.json` 及 `.example` | 页标题、展示限制、字段元数据等；引用 sample 配置，不复制股票名单 |
| 修改 `config/navigation.json` 及 `.example` | 新增真实观察池入口 |
| 新增 `ui_v2/pages/real-watchlist.html` | 结构和空态，不写业务样本 |
| 新增 `ui_v2/assets/real-watchlist.js` | API 驱动列表/详情、图表、状态与请求竞争处理 |
| 修改 `ui_v2/components/sidebar.js` | 主系统来源标识，不覆盖其他现有状态 |
| 按需修改 `ui_v2/assets/ui_common.css` | 与现有页面一致的状态和观察池样式 |
| 修改 `ui_v2/core/api.js` | 兼容的 strict 与真实超时支持，必须回归现有行为 |
| 新增 Python / Node 测试与隔离 fixture | 合成数据覆盖，不读取真实 Token、不联网 |
| 修改 `docs/README.md`、需求文档、HANDOFF | 实际交付地址、提交、证据和限制 |

禁止顺手重写 scan.py、选股策略、生产日报或整个菜单系统。只读缓存适配如需新增文件，说明职责并纳入测试。

## 8. 执行顺序与验收

### Task 1：后端只读通道

- [ ] 先用临时 SQLite 和合成 CSV / 报告写失败测试，再实现接口。
- [ ] 覆盖默认演示+观察池真实并存、动态名单、未知代码/口径、文件缺失、符号链接、SQL 参数、报告部分失败、快照冲突、字段白名单和非有限数值。
- [ ] 校验手→股、千元→元仅转换一次；none/qfq 口径明确。
- [ ] HTTP Handler 测试未登录401、已登录可读、既有静态/模型/数据源路由不回归；验证 GET 从不触发供应商、模型或写库。

### Task 2：共享数据来源提示与观察池页面

- [ ] 先补 api.js 的 strict、实际超时、重试/去重与旧行为测试。
- [ ] 实现动态来源提示、列表、搜索、详情、图表/表格、原始财务和校验说明。
- [ ] Node 测试覆盖空态/失败/部分成功/401、股票和口径切换竞争、旧响应、旧缓存、NaN、0 与空值区别、缺失财务、快照冲突和来源标签不串页。
- [ ] 用仅合成数据的独立 fixture 在 Chrome 操作。fixture 不访问项目真实配置、不连接供应商，不允许写生产目录。
- [ ] 独立审查；修复重要问题后再部署。

### Task 3：Windows 发布与真实只读验收

- [ ] 本地运行全部 Python / Node 测试、语法检查、git diff --check。当前79+31为回归基线，新增测试计数另报，不能只写“测试通过”。
- [ ] 保存部署前 data/demo 和真实快照的文件哈希，以及 params.yaml / 模型 settings.yaml 校验值；禁止输出文件内容或凭据。
- [ ] 推送原 fork 分支和 PR1，核对 Windows 主机与提交后快进部署；只在必要时重启 Python 服务，不重启或改动 DSH 模型配置。
- [ ] Windows 重跑全部测试。用管理登录会话检查页面、JS、来源接口、列表和六只详情均可读；临时会话完成后注销，令牌不打印。
- [ ] 在 Mac Chrome 实际访问 Windows 的 Tailscale 地址，验证侧栏入口、真实快照标识、六只名称、日期、每只详情、口径切换、图表/表格与财务空态；刷新仍正确。保留不含凭据的截图。
- [ ] 页面刷新只读：演示库、真实快照、配置哈希均未变；不产生新的供应商请求、采集日志或数据库文件。
- [ ] 在其他业务页确认主系统仍显示演示模式，观察池的 real_sample 不影响全站模式。
- [ ] 更新 docs 的功能提交、部署提交、URL、测试数量、截图证据和剩余限制。文档在 Windows 项目中存在，真实行情仍被 Git 忽略。

本期最终验收语句应为：用户能在浏览器看到六只真实股票的历史快照，来源和口径明确，完整选股仍未验收。不要写“真实交易系统已完成”或“已切换全站真实数据”。

## 9. 给 Trae 的启动提示词

> 请在我的 fork deepseek-harness-quant 上执行 docs/superpowers/plans/2026-10-25-real-watchlist-for-trae.md。先读 docs/README.md 与当前验收记录，再实现独立的 /real-watchlist 和全站主系统数据模式提示。沿用现有分支和 PR1，先测试后实现、独立审查、部署 Windows 后用 Mac Chrome 验收。不要读取或输出 Token，不调用供应商，不切换生产数据源，不上传真实行情。完成后报告浏览器访问地址、实际提交、测试结果和遗留问题，并更新 Windows 项目 docs。
