# Tushare 配置页面 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to execute the authorized user request. No extra design confirmation needed: user explicitly requested the page and clarified both HTTP/HTTPS Pro-compatible relays.

**Goal:** 在现有fork和Windows服务提供安全可用的Tushare Token/官方及中转地址配置页。
**Architecture:** 独立DataSettings服务保存现有params；受保护HTTP接口；原生网页API驱动；动态JSON验证元数据；合成fixture验收。
**Tech Stack:** Python标准库、PyYAML、unittest、原生JS、Node test、Chrome CUA。

## Global Constraints

- 现有分支 codex/privacy-provider-settings / PR1；用户数据与真实凭据不动。
- 登录、精确Origin、X-Quant-Request:1；Token不回显、不留浏览器存储。
- HTTP需明确确认；切地址需新Token；DNS检查+连接IP固定；HTTPS证书验证；不跟重定向。
- JSON元数据配套.example；只手动验证保存版本，最多3次小样本Pro API请求；不全量下载/不切数据源。

## Task 1: 后端配置及传输（独立worker）
Files: 新deck/data_settings.py、config/data_sources.json及.example、tests/test_data_settings.py；改data/fetcher_tushare.py与config/params.yaml.example。
Interfaces: DataSettings(path=None, metadata_path=None, transport=None).describe()->DTO；save({expectedRevision,endpoint,token,allowInsecureHttp})->DTO；verify({expectedRevision})->{ok,revision,endpoint,checks}。错误复用deck.model_settings.SettingsError，固定安全code及HTTP status。describe字段：ok,revision,configured,endpoint,allowInsecureHttp,checks[{id,label}],testSymbol；endpoint实际完整URL。tokens未设置或模板占位不算configured。
- [x] 先写失败测试，再实现原子保留式配置写入、版本/HTTP确认/目的地址变更规则。
- [x] 写传输/verify失败测试，再实现DNS固定IP、限时/限响应/禁止代理及跳转、固定错误映射、单次并发与冷却。
- [x] 缓存配置变更测试先失败，再修fetcher的_PRO缓存重建。
- [x] 独立测试通过，交付明确接口说明，不自行提交他人文件。

## Task 2: 页面与动态菜单（Task1接口确定后，独立worker）
Files: 新ui_v2/pages/data-settings.html、ui_v2/assets/data-settings.js、tests/data-settings.test.cjs；改config/navigation.json及.example、ui_v2/pages/settings.html。
- [x] Node失败测试覆盖纯表单校验/保存payload/切目的地址/HTTP确认/未保存禁止测试/部分权限与网络错误说明。
- [x] 实现匹配现有设置页的深色中文UI，GET使用LW.api.get bypass/retry0；POST同源JSON。无浏览器Token存储或Token回填。校验结果使用DOM textContent。
- [x] 导航配置添加「数据源配置」，模型设置页互相链接。保存空Token保留已保存值。

## Task 3: Handler集成与隔离浏览器fixture（root）
Files: 改deck/deck_server.py/tests/test_deck_security.py；新tests/run_data_settings_fixture.py。
- [x] 失败测试：GET页/API需认证；POST保存/验证需认证与精确Origin；错误不泄密。
- [x] GET /data-settings，GET /api/data-settings/tushare，POST同路径保存，POST /api/data-settings/tushare/verify调用DataSettings；self.server.data_settings可注入，默认复用单服务实例保证并发/冷却。
- [x] fixture只临时合成配置和假公网resolver/transport，路由允许列表，不暴露业务/真实文件/通用代理。
- [x] Chrome合成Key操作并保存截图，测试后清理fixture进程。

## Task 4: 审查、发布及Windows验收（root）
- [x] 任务及整合独立审查，修复阻塞；完整Python/Node、语法及diff验证。
- [ ] 更新docs/API配置.md、HANDOFF和本地session交接，推送现有PR。
- [ ] Git bundle+SHA核对部署Windows，保留params.yaml用户修改，仅重启Python；线上只读验证，不写真实Token，不发真实验证请求。
- [ ] Chrome确认生产配置页可见；需要时仅复用原管理Token登录，不输出日志。保存截图交付。
