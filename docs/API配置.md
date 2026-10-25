# 模型与 API 配置

量化界面的「模型与 API」入口为同源 `/settings`。它使用 DSH 的服务商、模型目录、配置与凭据存储；不是完整 DSH GUI。所有页面、业务 API 与量化桥接都需要登录。控制页只支持已实现的聊天桥接；删除、解锁、清空、恢复会话不在本版支持范围。

## 首次登录

启动量化服务器后，在服务端项目目录执行：

```sh
python3 -m deck.web_security --show-token
```

Windows / WSL 部署可在 Windows 终端执行（先将路径替换为实际 Linux 项目目录）：

```powershell
wsl.exe -d Ubuntu -u jack -- bash -lc 'cd /path/to/deepseek-harness-quant && python3 -m deck.web_security --show-token'
```

若使用自定义 DSH_HOME，读取令牌的终端应使用与服务进程相同的 DSH_HOME。默认令牌位于项目 `harness/home/.quant-web-token`，不在网页静态目录。把命令在本地终端显示的值填入登录页；不要写入 URL、截图、工单或聊天。令牌不在启动日志中打印。退出登录会撤销当前会话；登录状态会过期。

## 原生与兼容服务商

1. 选择运行时动态返回的服务商。原生服务商可只填写 Key 后保存，不必编造协议、模型列表或地址。尚未配置的服务商可能没有模型；保存 Key 后刷新目录。
2. 自定义兼容服务商需填写稳定 ID（小写字母开头，仅含小写字母、数字与连字符）、协议、HTTPS API 地址、精确模型 ID（每行一个），可填写显示名称。协议选项来自后端元数据。地址不得包含用户密码、查询参数或片段，也不能指向本机、私网或元数据地址；解析后的地址也会检查。
3. Key 输入不会被回填，保存成功后清空。空白表示保留已有 Key，不表示删除。Key 由 DSH 凭据接口写入，网页不另建凭据库、不使用浏览器存储保存 Key。
4. 「移除 Key」仅移除对应凭据，保留服务商配置和模型列表。环境变量来源及只读凭据不能在此编辑或移除，需在运行环境管理。
5. 「设为新会话默认」仅影响新会话，已有会话保留原选择。设置默认时会清除旧模型的显式推理强度，由新模型自身能力决定默认值，避免继承不兼容的 `max` 等参数。模型来自 DSH 本地目录，本页不会自动发现模型，也不会发送付费测试请求。正常聊天会将上下文发给选择的服务商；兼容服务商的目标地址在页面明确显示。

配置和 Key 是分步写入的。如果配置成功、Key 写入失败，页面会明确显示部分失败并刷新版本；请重新输入 Key 重试。版本冲突时刷新目录后重新操作；刷新会清空未保存的表单，请先记录非敏感配置。加载或保存失败不会显示为成功。

rc.6 需要本仓库的 `quant-model-settings` 兼容插件才能写入新会话默认模型。更新包含该插件的新 profile 后必须重启 DSH；仅重启 Python 页面服务不足以加载新插件。插件只开放受限的默认模型读写，不提供通用管理 RPC 隧道。

## 隐私边界

会话遥测默认关闭与完全离线不是同一件事。普通模型请求仍发送 system、对话、工具调用与结果，并可附带稳定随机 UUID 和会话 ID；文件内容若进入工具结果，后续可能进入模型上下文。FULL 遥测可上传会话事件、工作目录、元数据与部分错误；FEEDBACK_ONLY 可包含反馈前事件。提供商的保存、训练和处理政策不由本次代码审查证明。workspace-write 也不等于隔绝所有个人文件读取。详细证据见 [隐私审查](reviews/2026-10-25-privacy-and-provider-settings.md)。

导航由 `config/navigation.json` 驱动，缺失时读取 `.example`；通过已认证的 `/api/navigation` 返回，设置页没有硬编码厂商列表。HTTPS 反向代理需正确设置 `QUANT_PUBLIC_ORIGIN`；写操作要求严格同源与请求头。

## 本地验证（无真实 Key 或模型请求）

```sh
python3 -m unittest discover -s tests -p 'test_*settings*.py'
python3 -m unittest discover -s tests -p 'test_*security*.py'
node --test tests/model-settings.test.cjs
python3 tests/run_settings_fixture.py --port 13187
```

手动打开 `http://127.0.0.1:13187/settings`，使用固定合成令牌 `quant-fixture-token` 登录。填写任意合成 Key，保存原生服务商后选择模型、设为默认、刷新并移除 Key。兼容地址 fixture 仅允许 `https://api.example.com/v1`，不执行 DNS 或外部网络调用。`--partial-key-failure` 可验证配置提交后 Key 写入失败的提示。fixture 仅绑定 loopback，退出进程即丢弃临时令牌及状态。
