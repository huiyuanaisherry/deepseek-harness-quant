# 隐私审查与多厂商 API Key 页面可行性

日期：2026-10-25（Asia/Shanghai）

审查代码：`9f72ab7e64799aecfc79cf3b913359acea1dd9b9`。本地和 Windows WSL 部署的提交一致。运行时为 `@deepseek-ai/dsh@0.1.0-rc.6`。

本次只读审查量化项目和已安装 DSH 的公开包代码，并对运行服务做有限验证；未读取真实凭据、聊天历史、个人文档或持仓文件，未修改线上程序。不是完整依赖供应链审计，也未进行长时间抓包，因此不能据此保证绝无信息外传。

## 结论

未发现量化项目暗中提取浏览器密码、浏览历史、SSH 私钥、剪贴板、摄像头或麦克风信息并上传给作者的代码，也未发现第一方隐藏收集端点。

但存在已验证的任意文件读取漏洞，当前服务又已通过 Tailscale 开放给可访问该设备的网络成员。该漏洞可能暴露运行用户可读的个人文件和未来配置的 Key，必须先修复。没有证据表明该漏洞被他人利用。

多厂商配置页面可实现，而且 DSH 当前版本已经自带 Settings → Models 页面。推荐复用其设置和凭据 API，补好量化项目的入口、访问保护和桥接兼容性。

## 1. 已确认的文件读取漏洞（高风险）

`deck/deck_server.py:638–643` 的 `/dl/` 下载接口，将请求后缀直接交给 `Path` 拼接并读取，没有目录边界检查。绝对路径会覆盖预期的 `BASE/output` 前缀。

`deck/deck_server.py:531–537` 的 `/v2/` 静态文件接口虽然删除 `..`，但同样没有处理绝对路径后缀；仅替换字符串不是有效的目录保护。

仅用公开文件完成了线上复现：请求 `/dl//home/jack/apps/deepseek-harness-quant/README.md` 返回 HTTP 200，响应 SHA256 与公开仓库 README 完全相同：

`0b1e12fa96ea1a0934eb5cb0a88d4cec6a6fa1a7a6b1ebc536a936e104eef11c`

没有请求任何真实凭据或个人文件。普通 `../` 形式的测试返回 404，不能据此认为已防护；本次部署没有 output 目录，绝对路径形式仍成功。

原程序监听 loopback，但 Windows 上已通过 Tailscale Serve 将 8787 转发至本地服务。入口不是公网服务；访问权限仍取决于 tailnet 访问策略。量化 HTTP 处理器没有应用级登录验证，因此可到达入口的客户端没有第二道身份检查。

建议：使用规范化路径与允许目录的包含关系校验，拒绝绝对路径和越界路径，并考虑符号链接；补充针对两条路由的回归测试。修复前不要保存真实 Key 或导入个人资料。

## 2. 哪些数据会去模型厂商

量化控制页主动聚合择时、候选池和持仓快照：`ui_v2/pages/control.html:508–568`，其中 `528–531` 明确包含持仓代码、名称和数量；`614–616` 在人格聊天请求中携带快照。

挂载中的桥接插件 `harness/home/profiles/web/plugins/dsq-quant-bridge.js:226–240` 将快照放进子代理提示词，并用 `toolFilter: {allow: []}` 禁用该人格子代理的工具。后续快照也会附加到消息中。

另一个桥接实现 `harness/plugins/dsq-quant-bridge/index.js:115–129` 将快照放入 system prompt，再调用模型接口。

这属于明确的产品功能，不是隐藏上传给作者。但它可能包含个人投资信息，建议界面明确显示发送范围，并提供默认关闭的“附带持仓”选项。

当前页面调用 `/quantapi/*`、`/niuapi/*`，实际挂载插件提供 `/quant/*`，两者不一致；因此此次确认的是代码中的数据流设计，未证明当前部署已成功把持仓送给模型。持仓也可能是本系统模拟/决策记录，不能据此推断已接入真实券商账户。

## 3. DSH 遥测、标识和工具权限

以下路径相对服务器 `harness/node_modules/@deepseek-ai/`：

| 行为 | 证据 | 结论 |
| --- | --- | --- |
| 会话遥测默认 DISABLED | `dsh-base/cordis.patch.yml:129–160` | 本次运行进程未设置 DSH_TELEMETRY_MODE / DSH_TELEMETRY_DISABLED，量化项目补丁无遥测覆盖，settings 没有遥测命名空间；与默认关闭一致，未做长期流量证明 |
| FULL 模式上传会话事件、工作目录、会话元数据及部分错误 | `dsh-session-telemetry/lib/index.js:147–174,255–266`；`dsh-session-telemetry-otel/lib/index.js:160–179` | 不能将 FULL 描述成只收匿名统计；默认端点是 `https://harness-telemetry.deepseeksvc.com/v1/logs`，基础配置未装内容脱敏规则 |
| FEEDBACK_ONLY 可发送反馈前的会话事件 | `dsh-session-telemetry-otel/lib/index.js:167–179`；`dsh-command-feedback/lib/index.js:46–69` | `/feedback` 与普通 UI 点赞不是同一行为 |
| 普通模型请求附带稳定随机 UUID 与会话 ID | `dsh-llm-deepseek/lib/index.js:536,570–584,752–753` | 即使会话遥测关闭也会发送；随机 UUID 保存在 `.anonymous-user-id`，不是由姓名/主机/IP 派生，但可关联请求 |
| 模型收到 system、对话、工具调用与结果 | `dsh-llm-deepseek/lib/index.js:70–137,584` | 文件内容若进入工具结果，后续可进入模型上下文；模型提供商的保存/训练政策不在此次代码审查证明范围内 |
| workspace-write 不限制全部读取 | `dsh-fs-sandbox/lib/index.js:70–89`；`dsh-sandbox-local/lib/index.js:22–49` | Linux 外部目录可读，不应把它当成个人文件隐私隔离；实际后端和授权仍影响可执行操作 |
| UI 点赞/点踩本地保存；导出为浏览器下载 | `dsh-message-feedback/lib/index.js:289–324`；`dsh-session-log-export/lib/client.js:114–128` | 未发现这些流程自动上传到厂商 |

在一次连接快照中观察到 Python 服务有一个公网 HTTP 连接，单凭 IP 和端口无法认定传输了个人信息；未捕获其请求体。静态代码存在正常行情抓取行为。

## 4. 凭据与访问边界

当前部署的 `harness/home/.credentials.yaml` 不存在，此结论仅来自文件存在性检查。

量化项目的接入脚本将 Key 写入明文 YAML（`scripts/接入API.py:45–64`）。验证请求发往官方 DeepSeek `/models`，没有发现另发作者端点。

DSH 的托管凭据同样是本地明文，但 POSIX 上使用 0600 文件权限和原子写入，保留其他条目；读取优先级是继承的进程环境 → 托管凭据文件 → 项目 `.env` → DSH home `.env`。证据：`dsh-credentials-local/lib/index.js:13–44,338–359`。0600 不能防御同一运行账号的任意文件读取漏洞。

桥接插件配置 CORS `*`，且聊天/历史处理器没有自己的身份校验。Python 的 `/api/proxy/*` 又是宽泛的 DSH 代理；在增加凭据管理前，需要审查、限制其能力，不能简单开放完整管理 API。浏览器跨站利用还受到 DSH 宿主和浏览器私网访问机制影响，未进行攻击验证。

行情 Token 会发送给配置的数据源端点，Tushare URL 支持自定义：`data/fetcher_tushare.py:27–43`；备用源使用 X-API-Key。不要把其他人的数据代理地址当成官方服务。

## 5. 多厂商配置能力

当前 DSH rc.6 已包含原生 Models 设置页：新增/编辑/删除 Key、内置厂商、自定义厂商、API Base URL、协议、模型目录和可用模型查询。无需为此升级运行时。

证据：`dsh-web-app/cordis.patch.yml:186–192`；`dsh-client-ui-settings-models/lib/client.js:541–570,1108–1126,1444–1460,1706,2448–2515,2714`。

内置目录包括 OpenAI、Anthropic、Google、DeepSeek、Moonshot/Kimi、MiniMax、Mistral、Groq、OpenRouter 等可用 API Key 接入的厂商。具体展示应来自 DSH 的动态目录，不能把厂商列表写死。OAuth 专用路由不等同于可填写 Key 的厂商，不在此功能范围。

自定义协议支持 `openai-completions`、`openai-responses`、`anthropic-messages`；内置适配器可有其他原生协议。

DSH 已提供 settings.describe/mutate、credentials.describe/set/unset、llm.providers、llm.discoverModels 等 RPC。凭据状态描述不返回明文。配置和凭据分开保存，原生 UI 已处理部分失败和版本冲突。

设置位于 `settings.yaml` 的 `llm-pi-ai.providers` 字典，Key 存在 DSH 原凭据库，模型路由位于 `agent-default-model`。Key 可热更新；已有会话可能保留自身模型选择，不能把“保存 Key”误认为“已切换当前会话”。不要把 Key 填在普通 headers 设置中。

## 6. 配置页面方案（待确认，尚未实施）

推荐：先修文件路径漏洞和管理 API 的访问边界，再把 DSH 原生 Settings → Models 作为量化界面的正式入口接入；同时修正当前前端与桥接插件路由、远程 GUI 的 localhost 链接。管理入口需要登录/会话保护、同源写入校验和明确的访问范围，不能仅靠输入框掩码。保留 DSH 原凭据库和脱敏状态返回，避免在浏览器 localStorage、URL、普通业务配置或日志保存 Key。自定义 endpoint 的模型查询要明确提示 Key 发往哪个地址，并限制不安全地址和重定向。

备选：在量化界面新做轻量表单，但底层仍调用 DSH 的原生 RPC；视觉一致，维护字段、冲突和错误处理的成本更高。

不推荐：自行建立第二套 JSON/数据库 Key 仓库，或继续扩展仅支持 DeepSeek 的写文件脚本。

测试应覆盖目录越界、绝对路径、未登录访问与跨站写入、凭据不回显/不进日志、动态厂商目录、自定义模型、保存部分失败，以及当前会话和默认模型切换。功能验证使用合成凭据和本地模拟 API，不使用真实 Key 发出计费请求。

本报告是审查记录和待确认方案，不表示漏洞已修复或配置页面已上线。
