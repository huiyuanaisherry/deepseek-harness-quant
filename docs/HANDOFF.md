# 接手说明：隐私修复与多厂商 Key 配置

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
