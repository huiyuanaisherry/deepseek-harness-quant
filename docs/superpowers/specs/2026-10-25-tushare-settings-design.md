# Tushare 数据源配置页

用户明确要求网页配置 Tushare Token，并要求兼容与官方协议相同的 HTTP / HTTPS 中转。沿用现有用户 fork 分支和 PR1，完成后部署 Windows。页面与现有深色模型设置风格一致，独立入口 `/data-settings`，避免将行情 Token 与模型 Key 混淆。

## 数据与权限

- 继续使用 `config/params.yaml` 下 `data.tushare_token`、`data.tushare_api_url`，新增 `data.tushare_allow_insecure_http`。保留其他配置键与值，原子写入且0600权限；模板同步说明。无新凭据库，无真实 Key 测试。
- GET只返回是否已配置、经过安全检查的接口地址、HTTP确认状态、版本摘要、动态验证项目元数据和当前演示模式说明。Token不回显、不进浏览器持久存储/URL/日志/错误。
- POST保存要求当前revision。空Token保留现值；改变接口地址必须重输Token。HTTP仅在明确勾选明文传输确认时允许。HTTPS保留证书验证。
- `/data-settings` 与所有新API继承现有登录/同源/请求头/JSON大小限制；GET不得触发保存/外部验证。

## 传输与验证

- 官方/中转使用标准 Tushare Pro JSON 请求，完整URL按原样路径发送，不追加OpenAI式路径。允许http/https、公网DNS/IP；禁止userinfo、query、fragment、私网/回环/元数据地址和混合公私解析。不跟随重定向。
- 验证连接时DNS检查并固定实际连接IP，HTTPS保留原hostname的SNI/证书校验；关闭系统代理，设置超时及响应大小上限，原始上游错误不外泄。
- 保存不调供应商API。独立「验证连接」对已保存版本串行发送至多3次小样本查询：daily、adj_factor、fina_indicator；样本代码与标签等可变元数据放config JSON并提供.example。不下载全市场、不扫描、不调用模型、不切换数据目录。
- 各接口分别报告可用/空数据/凭据无效/权限不足/限流/连接失败，不把某个接口成功当成所有权限可用；验证限并发与短暂冷却，避免重复点击耗配额。验证结果为当前版本，配置冲突明确提示。
- 现有fetcher缓存的Tushare客户端应在Token或URL变化后重建，确保配置更新后续采集可用。

## 页面

字段：Tushare Token密码框、完整接口地址（官方地址默认，可切换中转）、HTTP确认勾选；已配置状态和明确的Token发送目标。按钮：保存、验证已保存配置、刷新。未保存修改时禁止误测旧配置；保存成功清空Token框。页面说明配置不等于数据已下载，当前演示目录不会自动切换。

## 验收

先失败后修复的单元测试覆盖配置保留、权限、原子写入、冲突、Token隐藏、切地址需新Token、HTTP确认、DNS/重定向/响应限制、安全错误、客户端刷新；HTTP Handler集成覆盖登录及CSRF；Node测试表单状态与错误提示。Chrome合成fixture验证保存/刷新/HTTP确认/逐项测试，fixture仅访问临时文件和假供应商。独立代码/安全审查后推送现有PR并部署；线上仅验证页面/静态/已认证API可读，不写用户Token或调用真实Tushare。
