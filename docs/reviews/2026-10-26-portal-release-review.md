# 门户状态治理发布审查

日期：2026-10-26。审查 Trae 提交 c01a5f2、3a63c07、7c79cdb；范围为首页方案 Task 1–3。Task 4–7 的真实采集、分析链、切换及调度未实施，不能称首页真实数据已接通。

## 发布前修复

- 合法 global_rotation 防守产物被错误要求含 widget.assets；改为校验实际生产者字段。
- tech_pitch.pool_date 未识别、无日期产物误报可用、ok=false 被当有效空结果；补业务日期与失败状态判断。
- 简报前置分析缺失时不能显示“已分析、暂无要点”，现标 blocked。
- 五福轮动 unverified 映射阻断；逐资产有效末日及跨面板日期保持一致，拒绝未来/重复日期；ret60 恰 61 条边界修正。
- 首页日期查询改纯只读，不构造 DailyCache，不建库；存在 WAL 时拒绝将主文件当完整快照。日期仅代表缓存最新观察日，不证明全市场完整。
- 聚合读取不再持久化市场收益缓存；首页停止自动实时采集及会调用更新端点的批量存活探测，明确显示尚无只读快照。旧端点其他调用方未作全面改造。
- 零字节 JSON 不再被健康统计视作绿色可用；网络失败会覆盖旧卡片状态；轮动请求启用 strict，避免旧缓存冒充当前成功。
- 轮动错误不向 API 透传原始异常文本；增加对应中文原因说明。

## 验证与发布边界

本地 Python unittest 179 项通过（2 项因可选依赖/SDK 跳过），Node 73 项通过，门户内联 JavaScript 语法检查通过。新发布回归测试覆盖实际轮动生产者 schema、无日期、失败空结果、简报前置缺失、映射/日期阻断及 GET 只读行为。

发布前 Windows 基线 a7b6022，两项服务 active；已保存 50 个受保护文件的 SHA256 与 DSH PID 到服务端私有 /tmp 基线文件。完成后补记 Windows 测试、版本、哈希、服务与 HTTP/浏览器验证结果，不以本地通过替代生产验证。

未执行全市场下载、生产数据切换、定时任务启用或交易。本轮程序发布不能消除尚未生成的数据，页面应明确显示这些阻塞。

## Windows 实际发布结果

- 功能提交 `99bdc2f` 已推送用户 fork，并通过 bundle 快进 Windows；仅重启 deepseek-quant.service，两项服务 active，DSH PID 23712 未变。
- WSL 虚拟环境由 uv 管理，不含 pip；安装 pyarrow 26.0.0。第一次安装受继承的代理连接失败影响，仅在该安装子进程去掉代理变量后成功，未修改系统代理或供应商配置。
- Windows Python unittest 179/179 通过、无跳过；使用 /home/jack/.local/opt/node22/bin/node 运行 Node 73/73 通过。
- 管理会话 HTTP 验证：根页面、portal_dash、wufu_rotation、portal_status.js、real-watchlist 页面及列表 API 均 200。门户 mode=demo、数据日 2026-05-15；机会池等 missing、数量 null；brief=blocked、schedule=blocked；五福轮动 blocked/input_missing，已不报缺引擎。
- 50 个受保护文件发布前后 SHA256 一致（私有模型/行情配置、演示数据和真实样本），服务端基线只留 /tmp 私有文件，不入 Git。
- Mac 内置浏览器可达生产地址，刷新后到管理登录页；Chrome 扩展连接失败，未完成登录后的完整交互验收。HTTP 登录测试使用现有管理令牌仅在服务端进程内存中读取，未输出凭据。
- 回滚入口：程序基线 a7b6022；若需回滚，先记录当前私有改动，以 git revert 对本轮程序提交生成回滚提交，或建立基线独立检出并沿原服务路径配置恢复。禁止 git reset --hard / git clean，禁止覆盖 harness/home/settings.yaml 等用户改动。已安装 pyarrow 可保留，不改变既有数据语义。

## 后续工作

真实数据与计算产物仍未接入门户，Task 4–7 未实施；保持演示库隔离。后续依据原方案先提交有界请求计划，再经授权采集、生成产物和切换。旧 live_endpoints / live_forward 其他调用方未全面改造，此次仅确保门户不自动调用这些有副作用的端点。
