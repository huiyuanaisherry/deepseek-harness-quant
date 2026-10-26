# 接手说明：隐私修复与多厂商 Key 配置

> 最新入口：`docs/README.md` 与 `docs/requirements/real-data-validation.md`。Windows 当前功能代码仍为 `a439c87`；本地分支已推送真实观察池提交 `8edfe1d`，但未部署到 Windows。六只真实样本采集和离线技术因子已验收，完整选股链路尚未验收。本文旧版本状态以文末最新记录为准。

## 当前状态（最终更新：2026-10-25）

用户授权的 fork 分支为 `codex/privacy-provider-settings`，草稿 PR 为 https://github.com/huiyuanaisherry/deepseek-harness-quant/pull/1 。未合并 master。

**Windows 已部署至功能提交 `74ed001f0bc70987757892911b97dde050b527ad`。Mac Chrome 真实模型测试已收到「连接成功」，刷新后记录仍在。** 当前默认为用户配置的 moark / DeepSeek-V4.1-Flash-1017，模型 Key 未被读取或修改。

26 项 Python + 20 项 Node 测试通过，独立审查通过。下文保留之前各阶段记录；遇到「尚未部署」「尚未验证模型回复」等旧描述，以本节和文末最新验收为准。后续 agent 无需重做部署/隐私审查/模型测试；按新的具体反馈继续。

## 已完成和证据

- 本地隐私审查见 `docs/reviews/2026-10-25-privacy-and-provider-settings.md`。未发现暗中窃取信息的第一方代码，但已验证任意文件读取漏洞；AI 正常调用仍会发送上下文及部分随机标识。不要将其描述为“绝无隐私风险”。
- `52de1f4`：登录/会话保护、文件路径边界、受限 DSH 配置接口。
- `8a6c382`：更新/导出/回测执行改为受保护 POST，堵住旧 GET 绕过写入检查。
- `430f730`：DSH rc.6 默认模型兼容插件。独立 Python/安全复审通过，无 Important/Critical；18 Python + 3 Node 测试通过。
- `8ebfce1`、`5a8a7ba`：中文配置页、动态菜单、客户端写入保护和文档、登录令牌说明。
- Chrome 实测通过：假 Key 保存、原生厂商模型目录更新、默认切换、刷新保留、移除 Key、自定义兼容厂商、部分写入失败提示。
- 隔离的真实 DSH rc.6 测试通过：读取 37 个厂商、保存合成厂商和假 Key、切换默认、恢复默认、删除测试凭据/厂商。没有调用模型、没有费用。
- UI 审查发现测试服务器仍可调用真实业务 Handler；`78d210a` 新增测试先失败（6 个子用例），再用测试路由允许列表隔离，22 Python + 10 Node 测试通过。

## 当前验收结果与下一阶段

- 最终整分支审查已通过至 `b067c0a`，无剩余 Critical / Important / MEDIUM。详细报告在本地 `.superpowers/sdd/final-review.md`。
- `b067c0a` 显式关闭被拒绝重定向和 HTTPError 的响应。新回归测试先失败后通过；`python3 -W error::ResourceWarning -m unittest discover -s tests -v` 最新 **23 项通过且无 ResourceWarning 输出**；Node **10 项通过**。
- `78d210a` 修复测试服务器隔离；重启后已用 Chrome 复验登录直接进入 `/settings`、导航显示合成数据、保存假 Key 成功且输入清空。旧测试进程已随中断消失，未继续使用旧 Handler。
- UI 初审曾因额度终止，但后来另一独立 final reviewer 完成了整分支审查，不要再将额度中断当成最终阻塞。
- 非阻塞维护观察：当前全局 fetch 包装仍可影响跨源 POST / 401；未发现当前业务调用的触发证据，最终 reviewer 没有将其列为阻塞。后续扩展第三方浏览器调用时应收窄到同源或使用 helper。
- **下一阶段是确认合并/部署方式及用户自行填写真实 Key**，不要自动将本地已通过等同线上已修复。部署必须加载新 Python 源码与 DSH profile 并重启两项服务；线上运行版本本轮没有变动。
- 若接手时分支尚未推送，执行下面的 SSH push 命令；若已推送，不重复发布或重做实现。PR 存在时继续原 PR，不重复创建。

## 技术决策（不要重做）

- 复用 DSH 现成厂商目录、设置和凭据库；不另建 Key 数据库，不将 Key 放浏览器存储、URL 或响应中。
- 原生厂商可以仅保存 Key；使用每个 provider 自己的 revision 和 settingsNs，不向 DeepSeek 根 namespace 强塞 pi-ai 字段。
- DSH rc.6 的通用 settings RPC **刻意不开放 agent-default-model**。不能再尝试只用 settings.mutate 改它；已经有小型 `quant-model-settings` 插件，通过原生 settings service 保存并限制 loopback/Origin/header/body。
- 自定义 HTTPS 地址禁止私网、userinfo、query/fragment；本轮没有自动模型发现或付费连通测试。
- 默认模型只影响新会话；旧会话不静默切换。
- 管理令牌和模型 API Key 是不同凭据。真实令牌只能用户在服务端本地通过 `python -m deck.web_security --show-token` 读取，不要把真实凭据打印到审查日志或聊天。
- `.superpowers/sdd` 是本地忽略的详细证据目录，包含 plan briefs/reports/diff packages、后端复审报告和进度账本；在另一台机器 clone 时不会存在，需参照此文及已提交 docs。

## 接手后的首个动作

```sh
git status --short
git log -8 --oneline
python3 -m unittest discover -s tests -v
node --test tests/*.cjs
```

先读本说明和批准的设计，检查分支远端/PR 状态，然后推进合并或 Windows 部署；不要重复 Task 1、Task 2、最终审查或已修复的 socket 警告。

## 本地验收与交付

```sh
python3 tests/run_settings_fixture.py --port 13187
# 浏览器打开 http://127.0.0.1:13187/settings
# 合成测试登录令牌：quant-fixture-token（不是生产凭据）
python3 tests/run_settings_fixture.py --port 13188 --partial-key-failure

git push -u origin codex/privacy-provider-settings
```

GitHub HTTPS 推送没有凭据；origin 的 push URL 已改为 SSH，`ssh -T git@github.com` 确认账户为 huiyuanaisherry，dry-run 成功。不要在输出中读取 keychain 或 token。

## 文件状态

| 文件 | 状态 |
| --- | --- |
| `.gitignore` | 已提交；测试与最终整体验收通过 |
| `README.md` | 已提交；测试与最终整体验收通过 |
| `config/navigation.json` | 已提交；测试与最终整体验收通过 |
| `config/navigation.json.example` | 已提交；测试与最终整体验收通过 |
| `config/web_security.yaml.example` | 已提交；测试与最终整体验收通过 |
| `deck/dashboard_live.html` | 已提交；测试与最终整体验收通过 |
| `deck/deck.html` | 已提交；测试与最终整体验收通过 |
| `deck/deck_server.py` | 已提交；测试与最终整体验收通过 |
| `deck/live_api.py` | 已提交；测试与最终整体验收通过 |
| `deck/live_patch.js` | 已提交；测试与最终整体验收通过 |
| `deck/model_settings.py` | 已提交；测试与最终整体验收通过 |
| `deck/web_security.py` | 已提交；测试与最终整体验收通过 |
| `"docs/API\351\205\215\347\275\256.md"` | 已提交；测试与最终整体验收通过 |
| `docs/reviews/2026-10-25-privacy-and-provider-settings.md` | 已提交；测试与最终整体验收通过 |
| `docs/superpowers/plans/2026-10-25-provider-settings.md` | 已提交；测试与最终整体验收通过 |
| `docs/superpowers/specs/2026-10-25-provider-settings-design.md` | 已提交；测试与最终整体验收通过 |
| `harness/home/profiles/web/cordis.patch.yml` | 已提交；测试与最终整体验收通过 |
| `harness/home/profiles/web/plugins/quant-model-settings.js` | 已提交；测试与最终整体验收通过 |
| `tests/model-settings.test.cjs` | 已提交；测试与最终整体验收通过 |
| `tests/run_settings_fixture.py` | 已提交；测试与最终整体验收通过 |
| `tests/test_deck_security.py` | 已提交；测试与最终整体验收通过 |
| `tests/test_model_settings.py` | 已提交；测试与最终整体验收通过 |
| `tests/test_quant_model_settings.cjs` | 已提交；测试与最终整体验收通过 |
| `tests/test_settings_ui.py` | 已提交；测试与最终整体验收通过 |
| `tests/test_web_security.py` | 已提交；测试与最终整体验收通过 |
| `ui_v2/assets/model-settings.js` | 已提交；测试与最终整体验收通过 |
| `ui_v2/components/decide.js` | 已提交；测试与最终整体验收通过 |
| `ui_v2/components/sidebar.js` | 已提交；测试与最终整体验收通过 |
| `ui_v2/core/api.js` | 已提交；测试与最终整体验收通过 |
| `ui_v2/pages/backtest.html` | 已提交；测试与最终整体验收通过 |
| `ui_v2/pages/control.html` | 已提交；测试与最终整体验收通过 |
| `ui_v2/pages/factors.html` | 已提交；测试与最终整体验收通过 |
| `ui_v2/pages/report.html` | 已提交；测试与最终整体验收通过 |
| `ui_v2/pages/settings.html` | 已提交；测试与最终整体验收通过 |

## 已发布交付状态

- 修改已推送到 fork 分支 `codex/privacy-provider-settings`。
- 草稿 PR：https://github.com/huiyuanaisherry/deepseek-harness-quant/pull/1
- 功能代码最终审查通过版本：`b067c0a`；之后提交仅更新交接文档。
- 23 项 Python 和 10 项 Node 测试通过，独立最终审查批准。
- Windows 运行服务尚未更新，master 尚未合并。下一位 agent 从本文件和计划中继续部署阶段；勿重复隐私扫描或使用真实 Key 做付费测试。
- 本轮本地合成测试服务已停止；如需演示，按上文命令重新启动。

## Windows 部署验收（2026-10-25，覆盖上文未部署状态）

- 已部署并重启 Windows / WSL 的 `deepseek-quant.service` 与 `deepseek-harness.service`（systemd user 服务），均为 active。
- 实际部署提交：`808bbd095bdca2b41263e3bb088a436b54295b15`，远端部署分支 `deployment/privacy-provider-settings`。随后本分支仅补充交接文档，无运行代码差异。PR 仍是草稿，未合并 master。
- Windows 访问 GitHub fetch 未及时完成，终止本轮 fetch 后，通过 SSH 传输 Git bundle；bundle verify 通过，并严格核对完整提交 SHA 后切换分支。没有复制 Mac 运行时或凭据。
- 旧代码回滚分支：`deployment-before-provider-settings-20261025`（`9f72ab7`）。回滚代码会恢复已知旧漏洞，只有明确需要时使用；在部署目录切回该分支，再 `systemctl --user restart deepseek-harness.service deepseek-quant.service`。
- 原有未跟踪的 `data/demo/stock_basic.csv` 保留；未更改现有数据、Key、默认模型或 Tailscale 暴露范围。
- WSL 环境重新执行 23 项 Python + 10 项 Node 测试，全部通过。
- Mac Chrome 实际访问 Windows 服务：`/settings` 跳转管理登录页；远程未认证 `/api/model-settings` 返回 401。
- 服务端临时认证会话验证：`/settings` 200，原生目录 37 个厂商，导航包含 `/settings`；会话已 logout 撤销。管理令牌未打印，未读取模型 Key，未调用模型。
- 新管理令牌由服务端生成。用户需在自己的 Windows 终端按 `docs/API配置.md` 获取令牌并登录，再填写真实厂商 Key。真实 Key / 付费模型请求不属于本轮验收。
- 后续 agent：不必再次部署代码或重复审查；若用户提供实际使用反馈，再据具体问题处理。详细主机连接资料仅保存在本地会话备份及用户 AGENTS.md。

## 会话未就绪修复（2026-10-25）

- 用户完成厂商配置后，在控制页发送测试消息出现「会话未就绪」。实测 DSH 服务正常，`/quant/sessions` 返回 0 个根会话，牛散目录正常。
- 根因：没有新建主会话入口；空根会话被过滤；首次成功读取不更新初始连接徽章。
- `c44d359` 增加受登录/同源保护的 POST `/api/chat/session`，固定调用原生 RPC `session.create`、空 payload，只返回校验后的 sessionId；不允许浏览器指定 cwd/preset/options，不自动发消息。
- 控制页增加「新建会话」、保留空会话、正确连接/空状态；`creatingSession` 防止创建期间误发旧会话。独立 reviewer 初审发现竞态，回归先失败后修复，复审 APPROVE 无阻塞。
- 本地及 WSL：25 Python + 13 Node 测试全部通过。Windows 已更新到 `c44d35958b49d7baa6bba4a642c054186e0f1e41` 并只重启 Python 页面服务；DSH 未重启，用户的 settings.yaml 修改及凭据保留。
- 线上验收：认证后 control HTML 存在新按钮；POST 成功创建一个空主会话，桥接列表可见且 recent 消息为 []。未调用模型，未读取厂商 Key；临时测试登录会话已撤销。
- 用户浏览器因 Python 重启需使用原管理令牌重新登录，再打开 /control 选中主会话发送连接测试。目前仍没有实际模型回复证据，不能宣称模力方舟 Key 连通已验证。
- 另见控制页旧快照卡 `/api/harness` 返回404，和会话/模型调用不同；本轮未扩展快照功能。截图 `/tmp/quant-session-fix-login.png` 为部署后重新登录页。

## Chrome 真实模型调用与显示修复（2026-10-25，最终验收）

- 浏览器实测发现：内部工作区/技能说明被渲染为 user 消息；请求实际失败，但页面一直等待。原生 history 的 turn/end 错误码为 `UNSUPPORTED_REASONING_EFFORT`。
- 根因：原始 settings 中的 `reasoningEffort:max` 在切换自定义模型时被保留；当前模型无该能力元数据。`3314d9d` 默认模型写入同时 unset 这一模型所属字段，由新模型默认能力决定；已在 Chrome 对用户当前同一模型再次点「设为新会话默认」，未换模型或 Key。
- 桥接返回安全 turn 状态/固定错误码及 requestId，不泄露原始错误；根会话生成 UUID、牛散 followup 使用原生 MessageId；状态保留 requestId，不依赖最多 30 条的可见消息窗口。UI 等 turn idle 才判成功，错误立即结束等待，旧回复不被误认为新回复。
- 审查发现满 30 条消息时计数关联失效，已增加回归并修正；独立复审通过。提醒消息实际 source.kind 为 agent-instructions / skill-catalog / plugin，`74ed001` 只显示显式 user 来源或旧版无 source 的 user 消息，以及 assistant 消息。
- 运行快照未生成时显示明确空状态，不再将可选快照 404 显示为聊天连接故障。
- Chrome 按真实页面操作：登录 → 模型设置 → 保存同一默认模型 → 控制 → 新建会话 → 发送「你好，请只回复“连接成功”，不要调用工具。」 → 收到真实 assistant「连接成功」及「✓ 已回复」。原生 session.models 确认当前 moark 模型无显式 reasoningEffort。
- 清理最后两类提醒后只重启 DSH，使用原生 session.create 的 sessionId 恢复刚完成的测试会话，没有再次发模型请求；刷新 Chrome 后仅两条聊天消息，实际回复保留。原生 history 没有 tool/ 调用事件。
- 最后一次全量验证：本地及 WSL 26 Python + 20 Node 全过；后续仅一行提醒过滤调整，其 4 项桥接测试在两端通过，独立审查批准。
- 截图 `/tmp/quant-moark-real-reply.png`；Chrome 用户标签页 1660697005 保持 /control、已登录。管理令牌经仅内存/FIFO 方式复用，未输出日志、未落普通文件，FIFO 已删除；服务商 Key 未读取/修改。
- 生产目录仍以 data/demo 运行。真实模型连通成功不代表真实行情、运行快照或交易链路全部验收。当前没有额外待发模型请求。

## 真实数据抽样接入（2026-10-25，尚未切换网页）

- 用户询问 Tushare Token 位置及少量真实数据如何隔离验证。Token 由 `data/fetcher_tushare.py` 从 `config/params.yaml` 的 `data.tushare_token` 读取，`data.tushare_api_url` 应为实际接口地址。现已提供同源 `/data-settings` 页面管理这两项及 HTTP 确认开关；说明见 [API配置](API配置.md#数据源配置tushare)。远端 params.yaml 存在，未读取/打印其 Token，也未改动。
- WSL 已安装 baostock / akshare / tushare。本轮先验证无个人 Token 的 BaoStock，串行少量请求，不启动全市场更新。
- 成功目录：生产项目下 `data/real-smoke/20261025-161826/`。SQLite bars.db 含 000001.SZ、600519.SH 两只测试样本各 260 个交易日 × none/qfq 两种复权，共1040条；最新2026-10-23。仅用作连接/字段测试，不是选股建议。
- 同目录每只股票有 basic.csv、profit.csv（2026Q2）；检查了发布日不晚于当日。verification.json 记录 ok:true、demo_unchanged:true。这里只验证部分财务指标，不代表已取得全量财报或完整 PIT 验收。
- 初次尝试目录 `data/real-smoke/20261025-161708/` 保留失败记录。传 DailyCache 相对 db_path 时，其 _ro_uri 调 Path.as_uri 抛 ValueError 被读取函数吞掉，表现为 get_daily=None；调整调用方为显式绝对路径后成功。本轮没有修改 DailyCache 源码。
- data/demo/bars.db 大小/mtime前后相同；没有改动 systemd Environment，也没有重启或切换生产网页。网页仍使用 data/demo。
- 下一步依赖用户自行在服务端配置 Tushare Token；只需回复「已配置」，不要让其把 Token 发聊天。之后验证官方接口权限，使用独立目录补全数据与质量校验，再处理旧脚本写死 data/cache 的路径、全市场覆盖/候选池/日报产出，最后才能考虑切换网页与定时任务。

## Tushare 数据源配置页（2026-10-25，本地完成，未部署）

- 新增 `deck/data_settings.py`、`config/data_sources.json(.example)`、`/data-settings` 页面与 `/api/data-settings/tushare` 保存/验证接口，`config/navigation.json` 动态菜单与「模型与 API」页互相链接。只读写 `params.yaml` 的 `data.tushare_*` 三项，不改动其他配置键。
- 安全规则：登录 + 精确 Origin + `X-Quant-Request: 1`；Token 不回显、不进浏览器存储或日志；首配或换址必须新 Token；HTTP 需显式确认；DNS 仅允许公网并固定连接 IP，HTTPS 保留 SNI/证书校验，不跟随重定向、不走系统代理，含总时限与响应体上限；配置文件 SHA-256 作版本号，`tempfile` + `fsync` + `os.replace` 原子写入，POSIX 0600 / Windows icacls ACL。
- 验证只对已保存版本串行请求 `daily`/`adj_factor`/`fina_indicator` 小样本，逐接口返回可用/无数据/凭据/权限/限流/网络/错误；进程级单次并发与冷却，未真正发起上游请求不消耗冷却。验证结果不代表全部权限，也不下载或切换数据。
- 页面显示数据模式（`LWQUANT_CACHE_DIR` > `data.cache_dir` > 默认 `data/cache`，含 demo 段时提示演示数据），说明保存/验证不会切换目录。
- 验证：Python 53 项、Node 31 项、`py_compile`/`node --check` 全过；外部 Chrome 合成 fixture 已逐项验收（首配缺 Token、保存、三项验证、换址缺 Token、HTTP 未确认、确认后保存、刷新清空），截图留存但未提交。
- 尚未推送 PR，未部署 Windows，未读取或写入真实 Token，也未发起真实 Pro 请求。fixture 进程已停止。

## Tushare 配置页发布（2026-10-25，覆盖上文未部署状态）

- 用户要求先发布现有版本。功能提交 `cc0fc73359288c1c4c232d053aeea3193d2edc63` 已推送 fork 的 `codex/privacy-provider-settings` 并部署 Windows / WSL；PR1 继续保留，未合并 master。
- Windows 部署分支 `deployment/privacy-provider-settings` 通过已验证 Git bundle 快进更新；回滚代码分支 `deployment-before-tushare-20261025` 指向 `74ed001`。未覆盖用户修改的 `harness/home/settings.yaml` 或数据目录。部署前后 `config/params.yaml`、`harness/home/settings.yaml` SHA256 校验一致。
- Windows 53 项 Python、31 项 Node 测试通过。重启 `deepseek-quant.service`，它与 `deepseek-harness.service` 均 active。Node 使用 `/home/jack/.local/opt/node22/bin/node`，非交互 shell 的 PATH 没有 node。
- 已认证 HTTP 检查：`/data-settings`、`/v2/assets/data-settings.js`、`/api/data-settings/tushare` 均 200；API 显示 configured=false、mode=demo。仅内部使用管理令牌建立验收会话，随后注销；未读写真实供应商 Token、未调用供应商。Mac 经 Tailscale 访问页面返回登录跳转303，未认证配置API返回401。
- 已知兼容问题尚未修复：配置页验证向完整 URL 原路径 POST，而 Windows 实际 Tushare 1.4.29 SDK 会追加 `/{api_name}`（假Token、mock网络复现）。部分标准中转可能验证成功但正式采集404。后续应统一验证和采集传输，并覆盖已安装 SDK 的路径行为。不能把本次发布视为真实取数验证通过。

## 六只真实样本验收与项目知识记录（2026-10-25）

- 用户明确要求项目知识随 Windows 系统保存，不使用 Mac 外部知识库。索引为 `docs/README.md`；需求、当前验收和下一阶段均在 `docs/requirements/real-data-validation.md`。二者随 fork 和 Windows 项目同步。
- 功能提交 `a439c87d93510fb94d87fd9b794464a43b5bae04` 已部署；`0710dfd` 为本轮第一阶段实现。远程通过已验证 bundle 快进，不覆盖配置和演示数据；后续文档提交不改功能。
- 已配置 Token 仅保留服务端；未再次输出、写入文档或提交 Git。实际采集统一使用配置页同一 PinnedTransport，绕过终端代理，不追加 SDK API 路径；配置页/实际采集不一致问题已修复。
- 两年六只样本：000938.SZ、000977.SZ、000063.SZ、603019.SH、601138.SH、688041.SH。全部通过；最新2026-10-23。none/qfq各2884行，共5768行；披露日期校验后财务47行；两只各10个缺失日有全天停牌证据。真实记录仅存在服务器 `data/real-smoke/sample/`，已新增 Git 忽略项，不能上传 CSV 或数据库。
- 私有报告 `verification.json` 显示 passed=true、demo_unchanged=true；重复写入读回一致、重复键0、quick_check=ok。`strategy_readiness.json` 六只 technical_ready、strategy_acceptance=false；财务季度口径、历史ST、全市场估值与外部因子未验收，不得冒充完整选股成功。
- 重现命令（项目目录、WSL）：`.venv/bin/python -m data.real_data_sample --config config/real_data_sample.json --as-of 2026-10-25`；随后 `.venv/bin/python -m data.sample_strategy_check --config config/real_data_sample.json`。这是固定快照；改变日期范围/历史长度需要新的 output_dir，窗口冲突会在写 bars 前拒绝。
- 修复了 Windows pandas3 含空财务值时字符串拼接报错，并新增停牌证据验证及至多2次NETWORK重试；不重试权限/凭据/限流错误。通过独立整体审查，所有重要问题已修复。
- Windows 79Python+31Node全过（含实际安装Tushare SDK的合成pro_bar测试），服务 deepseek-quant/deepseek-harness 均active。原有 params.yaml、harness/home/settings.yaml 校验值一致，网页仍以 data/demo 运行。
- 下一位 agent 从需求文档的「下一阶段顺序」继续：先历史ST与按披露日期的财务三表/单季转换，再处理旧scan路径/日期/覆盖阈值与候选池/日报，不必重做六只采集、隐私扫描、Key页面或Mac知识库登记。

## 真实观察池只读页面（2026-10-25，本地实现与合成验收，未部署）

- 依据 `docs/superpowers/plans/2026-10-25-real-watchlist-for-trae.md` 实现只读观察池。功能提交 `8edfe1d`（14 个文件，+2314/−25）已推送 `origin/codex/privacy-provider-settings`；PR1 https://github.com/huiyuanaisherry/deepseek-harness-quant/pull/1 仍是草稿，本轮未改 PR 说明（本机无 `gh`，HTTPS 无凭据）。
- 新增 `/real-watchlist`（登录保护）与三个 GET：`/api/data-context`、`/api/real-watchlist`、`/api/real-watchlist/stocks/{code}?adjust=qfq|none&revision=...`。页面与接口均在 `_gate()` 之后，响应 `Cache-Control: no-store`；未登录 API 401、页面 303 到 `/login`。
- 名单只来自 `config/real_data_sample.json` 的 `symbols`，Python/HTML/JS/`config/real_watchlist.json` 都不写股票代码。新文件：`deck/real_watchlist.py`、`ui_v2/pages/real-watchlist.html`、`ui_v2/assets/real-watchlist.js`、`config/real_watchlist.json(.example)`、`tests/test_real_watchlist.py`、`tests/real-watchlist.test.cjs`、`tests/api-client.test.cjs`；修改 `deck/deck_server.py`、`ui_v2/core/api.js`、`ui_v2/components/sidebar.js`、`ui_v2/assets/ui_common.css`、`config/navigation.json(.example)`。
- 只读与安全边界：SQLite 仅 `mode=ro`（不建库建表、不用 `immutable=1`）；列为服务端白名单，SQL 参数化；路径限制在项目 `data/real-smoke` 下并拒绝父目录/目标符号链接；revision 由配置投影与文件 size/mtime 生成，读前读后复核，变化返回 409 `SNAPSHOT_CHANGED`，前端重取一次列表；NaN/Infinity 转 null；tushare 手/千元经 `normalize_units` 只转一次；异常不原样透传；GET 不触发供应商、模型、采集或写库。
- 全站侧栏新增主系统数据模式：`demo`→「主系统：演示数据」、`cache`→「主系统：缓存数据」、取不到→「主系统数据模式未知」，不默认真实。观察池页额外显示「此页：真实历史快照 · 小样本观察池」与实际截至日，均来自 API。`ui_v2/core/api.js` 新增向后兼容的 `strict`、真正生效的 `bypass`（跳过缓存/去重）、AbortController 超时与计时器清理，其他页面默认行为不变。
- 本地验证：`python3 -m unittest discover -s tests` 94 项通过（1 项因未装可选 SDK 跳过）；`node --test tests/*.cjs` 59 项通过；`git diff --check` 通过。
- 合成 fixture 外部 Chrome 验收（`127.0.0.1:8791`，独立临时根目录，仅合成数据，不读真实配置/不联网）：登录后侧栏显示「主系统：演示数据」；观察池显示「此页：真实历史快照 · 小样本观察池 / 实际截至 2026-10-25」和「6 只样本 · 132 条行情 · 12 条财务」；6 只列表、搜索筛选（显示 1 只）、刷新后回到 6 只；详情图表 1 个 SVG、11 行行情、2 行财务、策略「未验收」与阻塞项；`none`→`qfq` 切换后首行收盘 10.35→9.77、口径文案更新；控制台无报错，网络仅 3 个本地只读 API。截图存于工作区 `trae-evidence/20261025-real-watchlist-fixture.jpg`，未提交 Git（不含凭据）。
- **Windows 未部署**：`jack@100.123.203.13` 与 `jack@192.168.31.86` SSH 均 `Permission denied (publickey)`，而 `http://100.123.203.13:8787/login` 返回 200，判断为 Windows OpenSSH 公钥授权丢失（本机公钥 `codex-ai-workbench`）。用户本轮选择先跳过部署。因此 `http://100.123.203.13:8787/real-watchlist` 尚未包含本期页面，Windows 测试重跑、真实六只页面验收、只读哈希核对均未执行。
- 恢复部署时：把 `8edfe1d` 打包为 Git bundle，SSH 传输后在 `deployment/privacy-provider-settings` 严格核对 SHA 并快进；部署前后保存 `config/params.yaml`、`harness/home/settings.yaml` 的 SHA256（不输出内容）与 `data/demo`、`data/real-smoke` 文件哈希；重启 `deepseek-quant.service`；Windows 用 `/home/jack/.local/opt/node22/bin/node` 重跑 Python/Node 测试；管理会话核对页面、JS、三个接口均 200 后注销；Mac Chrome 经 Tailscale 访问并对比只读哈希；其他业务页仍应显示演示模式。
- 遗留审查意见（低优先级）：`context()` 复用 `_rows` 全量读取，侧栏每次加载较重，可加短缓存或轻量摘要；`config/real_watchlist.json` 的 `sampleConfig` 未校验 root 前缀（只从项目配置读取，风险低）。

## 观察池修复与 Windows 发布（2026-10-26，覆盖上文未部署状态）

- 用户授权接手修复。`e68213b` 完成RW-01～06；`5483b8e` 修复实际浏览器超时恢复状态；`8198b0687758aa882fa1d207f5fc0208843b5742` 增加仅详情JSON协商gzip，为当前部署功能提交。文档后续提交不改功能。
- Windows SSH 使用1、公钥配置正常；WSL用jack。已通过verified Git bundle在deployment/privacy-provider-settings快进，回滚分支deployment-before-real-watchlist-20261026指向7fd486c。未合并master，PR1沿用。
- 正式地址 http://100.123.203.13:8787/real-watchlist 。主系统仍为data/demo，观察池显式只读data/real-smoke/sample。两项服务active，仅Python重启；DSH MainPID未变。
- 全部后端、前端及压缩改动均独立复审通过。Windows103Python+66Node全过；本地Python103项含1项可选SDK跳过。新增故障回归与现有测试均通过。
- 已认证HTTP核验页面/脚本/模式/列表和六只×none/qfq十二个详情，全部正常；asOf2026-10-23、技术指标可用、strategyAcceptance=false。gzip实测119356→28689字节，解压后484条完整。
- 配置params.yaml、模型settings.yaml以及demo/real-smoke共58文件SHA256前后完全一致。没有采集、切换生产目录或写行情库，没有修改Token。
- 浏览器验收部分完成：内置浏览器真实六只列表、紫光股份484行情/8财务/通过状态、浪潮信息详情已出现；复权切换及最终压缩版本完整复测未完成。Chrome插件连接策略错误，内置浏览器/网络后续超时。当前Tailscale经香港DERP，未建立直连，SSH也偶发连接超时；不能标记完整浏览器验收通过，也没有成功截图。
- 曾尝试仅Mac loopback绑定18787的临时SSH隧道，未能完成浏览器复测，已Ctrl-C终止；它不是部署依赖，用户仍使用100.123.203.13访问。ShieldsUp与网络安全设置均未改变。
- 后续只需在网络稳定后补Chrome正式URL的六只选择、复权/刷新、来源标签和截图验收；无需重做六项代码修复或Token配置。完整选股仍按需求文档补历史ST、季度财务、估值分位与外部因子。
