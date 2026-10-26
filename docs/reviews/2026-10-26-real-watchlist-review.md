# Trae 真实观察池实现审查

审查日期：2026-10-26。功能提交 `8edfe1d`，交接提交 `a9c5033`，设计基线 `7fd486c`。

结论：只读页面与数据通道基本实现，六只真实样本可读取；下列六项 P2 正确性问题应在部署前修复。本轮不修改功能代码，不部署服务。

## 实际验证

- 本地全量：94 项 Python（1 项可选 SDK 跳过）、59 项 Node 通过；git diff --check 通过。现有测试未覆盖下方复现的边界。
- 后端、前端分别独立审查。数据库修改仅在临时合成 fixture；前端用合成 VM/DOM 请求顺序复现。
- Windows 当前仍为 `7fd486cdcb7e59ef0e5f8427519d71f980c092ff`，两项服务 active，观察池未部署。
- SSH 按用户 AGENTS.md 使用 Windows 用户 `1` 与指定 identity 可正常连接，再调用 `wsl.exe -d Ubuntu -u jack`。以 jack 直接 SSH Windows 失败，不能证明公钥丢失；不要重置密钥或密码。
- 将新后端代码仅加载进 Windows 临时 Python 进程内存，读取已有真实快照：六只列表及 qfq 详情均成功，5768条日线、47条财务。演示目录及真实样本文件哈希前后不变，未落地新代码、重启服务、调用供应商或模型。
- 上述真实快照直接复现 RW-01：source.asOf=2026-10-25，而实际 scope.latestDate=2026-10-23。

## RW-01 / P2：实际截至日显示错误

位置：`deck/real_watchlist.py:375` 的 `_as_of()`。

优先使用 verification.as_of，把查询截止日当作实际行情日期。真实快照查询截止25日，日线只到23日，页面却会标“实际截至25日”。

修复：行情来源日期使用实际最新交易日，并核对采集报告日期。查询截止日另设字段表达。补周末截止日不同于最新交易日的测试。

## RW-02 / P2：报告与数据库矛盾仍显示通过

位置：`deck/real_watchlist.py:280` 的 `_verification()`，及 `_rows()` / `stock_detail()`。

复现：合成两日快照与报告原本通过；删除最新日行情后，详情只剩旧日一行，却仍返回 verification.passed=true、technical.available=true。新 revision 只代表当前文件，不能证明旧报告验证过它。

修复：实际 rows / latest_date 与 verification 对应股票元数据一致；技术指标还须匹配 readiness 的 history_count / latest_date。存在矛盾时409 SNAPSHOT_CHANGED。可选 readiness 缺失仅降级技术不可用。补删除/新增行情但未更新报告的测试。

## RW-03 / P2：WAL 更新绕过 revision

位置：`deck/real_watchlist.py:216` 的 `_revision()`。

复现：合成 SQLite 切 WAL，保留写连接并提交价格变动；主 bars.db 的 stat 不变，旧 revision 详情返回新价格且 revision 相同。文件版本未包含 bars.db-wal。

修复：安全检查并计入实际 SQLite sidecar 状态，保证只读事务一致性；或明确拒绝不支持的 journal 模式。不要用 immutable=1 假装数据不变。补保留 WAL 连接时旧 revision 被拒绝的测试。

## RW-04 / P2：连续详情409导致无限重试

位置：`ui_v2/assets/real-watchlist.js:512`。

每次列表成功把 snapshotRetries 清零，导致“列表200→详情409→列表200→详情409”无限循环。合成复现六轮后仍未显示手动重试按钮。

修复：自动恢复预算绑定一次用户操作，自动重取列表不能重置；完整一致详情成功或新的用户操作才可重置。补持续409最终停止的测试，修正现有认可自动清零的断言。

## RW-05 / P2：空列表刷新后迟到旧详情重新出现

位置：`ui_v2/assets/real-watchlist.js:502` 的 `loadList()` 及空列表成功分支。

复现：旧详情未返回，刷新得到新版本空列表，再返回旧详情；页面出现空列表旁的旧图表和已校验股票。列表刷新/空列表成功没有使旧 detailSeq 失效。

修复：刷新开始、列表版本与名单更换时立即作废旧详情；接受详情前校验当前 code、adjust、revision、请求序号。补刷新为空及移除选中股票的乱序测试。

## RW-06 / P2：迟到 context 覆盖不可用状态

位置：`ui_v2/assets/real-watchlist.js:488` 的 `loadContext()` / `renderContext()`。

复现：列表503先显示真实快照不可用，迟到 context 成功却把来源恢复为真实历史快照及日期，列表仍不可用。

修复：全局主系统模式与观察池当前可用性分开管理；观察池来源由当前成功列表/详情决定，context 不得恢复已失败的状态。补两个接口乱序及连续刷新测试。

## 发布前要求

1. 修复六项并增加回归，跑全量 Python/Node、独立复审。
2. 保留鉴权、只读模式、路径隔离、单位转换、空值与策略未验收状态，不动 Token / 演示配置。
3. 使用 Windows SSH 用户1部署，WSL 内用户jack操作，不因错误 SSH 用户修改公钥。
4. 真正部署后用 Chrome 验证六只、截至日23日、none/qfq、乱序/失败状态与哈希不变，再更新交接记录。
5. 当前合成浏览器验收和内存只读验证均不等于线上页面已验收。
