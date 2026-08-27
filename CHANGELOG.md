# CHANGE LOG

> **文档权重**：60（历史变更记录；不覆盖当前架构文档）

## [2026-08-27]

### SK8 / 高德联调收口与错误页审查修复

- 用户已手动验收 SK8 Clip 表单、地图拖动与高德原生关键词候选；地图输入被重新编辑时会立即清除旧地址和坐标，避免提交“新地点名称 + 旧坐标”。
- 同源高德代理收敛为固定资源白名单，并增加 JSONP callback 校验、按客户端限流、查询长度和上游响应体上限；浏览器仍只接触 Web JS Key，`securityJsCode` 保持服务端私有。
- Clip 上传请求只负责保存原片并进入队列，不再由 WSGI 请求创建无界后台线程；已有私有原片可显式重新入队，派生资源继续由独立 `process_skate_clips` Worker 生成。
- 视频预览遵循 reduced-motion 与精细指针能力；触屏和减少动态效果环境只展示 poster，仍可通过明确的 WATCH 操作播放。
- 板块错误页预览只在开发配置开放，生产配置固定关闭；修正测试隔离，避免为预览测试全局启用 Debug Toolbar。
- 本轮 Ruff 通过；73 项定向回归初跑仅有 5 项错误页测试隔离错误，修正后受影响的 12 项全部通过；Django system check 无问题，migration drift 为零。

## [2026-08-26]

### Django + HTMX 单体边界与本地启动检查

- `run.py` 自动切换到项目根 `.venv`，默认在启动前执行 Django system check、migration drift 检查和本地 migration；新增只读 `--check-only`、仅准备 `--prepare-only`、部署设置提示及显式跳过参数。
- 删除旧 Post/Category DRF ViewSet、Serializer、Router、OpenAPI Schema 与 Swagger UI，并从项目声明和本地虚拟环境清理 DRF/OpenAPI 及仅由其引入的依赖链。
- 高权重文档固定 Django Template + HTMX 为可见规划期内唯一 Web 架构；普通迭代和 Agent 不得为 SPA、独立前端或假设性客户端恢复通用 JSON Data API。
- 新增公开表面契约测试：`/` 必须渲染 Devenir 首页，`/Blogs/api/` 必须保持 404。相关 21 项回归、Ruff、Django check、迁移漂移、`pip check` 与 diff check 均通过。

## [2026-08-15]

### SK8 New Clip 与播放体验闭环

- `SkateClip` 新增 Clip / Line / B-roll 内容类型及可空地址、经纬度；New Clip 将元数据编辑、私有原片选择、本地预览和浏览器大小/20 秒预检整合为同一 Devenir 表单，服务端继续以 FFprobe 为权威裁决。
- 新建/编辑与旧媒体替换入口统一复用原片接入服务；“保存元数据”不会上传文件，“上传并处理”才进入媒体队列，探测失败时只保留私有草稿，避免公开无媒体占位。
- 高德 Web JS Key 可进入浏览器，`securityJsCode` 只由同源 `/_AMapService/` 固定目标代理读取；禁用、配置缺失或地图失败时安全降级为文本地点输入。
- Skateboard Index 的 WATCH CLIP 改为原地响应式播放浮层，桌面采用视频/资料双栏、移动端采用单列，并支持背景关闭、Esc 与触发按钮焦点归还。
- 全项目 454 项测试通过，1 项 PostgreSQL 专属并发测试按设计跳过；迁移无漂移、Django check、Ruff、JavaScript 语法以及 1440×1000 / 390×844 浏览器验收通过。真实高德凭据与拍摄样片仍需人工联调。

### SK8 视频流水线合并前一致性修复

- 将 main/preview/poster 改为 claim 版本化不可变 key；三项文件先写入未引用版本，再以数据库条件 UPDATE 整体切换，半途发布失败与 stale Worker 不再覆盖或混用当前公开资源。
- Index 按 FFprobe 落库的方向组成最多 2 个竖屏与 3 个横屏；WATCH CLIP 可恢复正式源并播放，媒体预览支持键盘焦点，上传页即时显示大小、分辨率、方向与时长。
- GC 增加私有原片孤儿、无引用派生版本与 ready 缺失资源对账；retention 改为 CAS 后删除，磁盘检查兼容尚未创建的配置根；Nginx 示例补 150 MiB 传输上限与 immutable 缓存。
- 使用真实 FFmpeg/FFprobe 的 73 项 SK8 定向回归、253 项 Boards 回归及 443 项全项目回归全部通过；唯一 1 项 PostgreSQL 专属并发测试按设计跳过。分支可从 `devenir @ d5c7104` fast-forward 合并；PostgreSQL 多 Worker 行锁与真实 Nginx 分发仍须在 CI/预发布验收。

## [2026-08-08]

### Board Index Category 映射边界修复

- Board 文章入口不再从模板回退到失效 Category；后端未提供可公开访问 URL 时直接隐藏“查看全部文章”，避免停用分类产生 404。
- Board 新文章 CTA 与 `PostCreateView` 统一要求有效创建权限和正常、唯一的 Category 映射；缺失、停用或重复映射不再展示错误入口，也不会错误预选分类。
- 增加缺失、停用、重复 Category 映射回归测试，并同步 V2GUIDE 与 Boards 开发文档的已完成状态。

## [2026-08-06]

### Board Index 文档一致性收尾

- 在修复夹具后的最终工作树重跑 47 项 Board Index/Policy/文章运行时组合回归，连同 Django check、Ruff 与 `git diff --check` 全部通过；`git ls-files "*HANDOFF*"` 为空。
- 通过 `run.py --plain` + Playwright 在桌面 1264 与移动 390 两种 viewport 下渲染三个 Board Index：所有 `documentElement.scrollWidth == innerWidth`、无横向溢出，`DISPATCHES / JOIN {Board} / 登录后申请 / 查看全部文章` 文本标记在 DOM 中确认，结构位置在 `</article>` 之后、page footer 之前。
- V2GUIDE 第 81 段清理过时的"K3 补文章入口+后端接线"待办描述，改为已完成事实；仅保留 REFUSE 模板统一接入为真实剩余项。

## [2026-08-04]

### Board Index 公开文章流

- Skateboard、Music、Coding Index 统一展示各自 Category 最新 5 篇公开已发布文章，并链接 Category 完整列表；草稿和 staff-only 文章不会进入该展示 QuerySet。
- 参与 CTA 由后端按匿名、可申请、待审核、有效成员和停用状态生成；Contributor/Editor/Manager 可进入安全预选 Category 的新文章页，Reviewer 进入带 Board 筛选的审核工作区。
- Board 权限申请页支持由服务端校验的 Board 预选；模板不读取 Group、staff 或角色字符串推导业务权限。
- 4 项新增文章流测试和 47 项 Board Index/Policy/文章运行时组合回归通过；Django system check 与 Ruff 通过。

### Board Index 专属内容闭环第一阶段

- Music 平铺 Record 增加排行、播放次数、收听分钟、封面和外链；Coding Project 增加 GitHub/local-only/external 类型、仓库/演示链接、封面和精选状态。
- 新增 Spotify 本地导出聚合命令，只写入 Wrapped 年度总量与艺人/歌曲排行，不持久化原始播放历史；本地 2025 导出已生成 13 条可读聚合记录，导出中不可展示的 `spotify:concept:*` 标识不会写入页面数据。
- Music Spotify/Apple 与 Coding Project 新增按 Board Manager Policy 隔离的业务 CRUD 后端；Padif 固定为浏览器本地存储/JSON 导入导出方向，不调用 Django 写接口。
- 合并 Music/Coding Devenir 页面，补齐 Skate Clip CRUD；主页功能菜单与各 Board Index 根据可管理板块显示快捷入口，所有写路由继续执行服务端 Policy。
- 管理页统一字号、表格网格与 Board 强调色；删除成功后显示位于固定导航下方、数秒自动消失的 Devenir 通知，并修复 DeleteView 因模型表单无字段 POST 而静默失败的问题。
- Ruff、迁移漂移和前序 31 项 Board Index/导入/权限定向测试通过；合并后的 Index/内容管理回归与 Django system check 继续通过。

### accounts_linear Stage 8 完成

- 全局审计确认运行时授权、审核入口、MFA 与 Board Policy 均不再读取遗留 `MyUser.is_reviewer`；删除模型字段与敏感字段兼容保护。
- 新增 `0011_remove_myuser_is_reviewer` schema migration，保留历史 `0002` 以支持旧数据库顺序升级；回归测试改为固定当前模型不再暴露该字段。
- 高权重文档将 Stage 0–8 标记为完成；Reviewer/Manager 的唯一业务事实来源为 `BoardMembership.role`，`is_dashboard_user` 继续只表达 Dashboard 外壳入口。
- 提交前 Ruff、迁移漂移与 Django system check 通过；全量 314 项测试通过，1 项 PostgreSQL 专属并发测试在 SQLite 下按设计跳过。

### Super Admin 与 Dashboard 特权会话收敛

- 本地开发统一以 `python run.py` 作为安全启动入口：默认加载本地 MFA keyring、启用 mTLS/MFA 强制并启动 Nginx；首次绑定使用 `--enrollment-mode`，显式降级调试使用 `--plain`。
- `/super_admin/` 维持每次 TLS 连接的客户端证书认证，并采用 15 分钟绝对有效期、5 分钟空闲超时和浏览器会话 Cookie；不尝试不可靠的“关闭单个标签页即失效”。
- Dashboard 的可选 7 天可信会话与 Super Admin 完全隔离；成员管理允许该可信会话进入，但所有写操作仍需当前 TOTP 换取一次性、绑定动作与目标的 capability。
- 更新 `V2GUIDE.md`、安全路线图、权限指南和开发说明，清理已完成却仍标为待办的阶段描述；生产证书吊销与 PostgreSQL 并发验收继续保留为未完成项。

## [2026-08-03]

### BoardMembership 生命周期 M3

- 新增 `/dashboard/memberships/events/` 与单 Membership 不可变事件时间线，支持按成员/操作者/原因、Board、事件类型及来源筛选，并使用快照展示已删除关联对象的历史语义。
- 将 Manager 连续性约束下沉到统一状态内核：最后一名 Manager 既不能停用，也不能通过角色调整或其他普通入口降级；Manager 交接仍在同一事务中先建立接替者。
- `/super_admin/` 的 Membership 默认 CRUD 永久只读；新增唯一 break-glass URL，仅在 MFA/mTLS 强制同时开启、证书与 privileged Session 匹配、重新验证 TOTP、精确确认目标且确为最后 Manager 时允许停用。
- M3 定向回归 56 项通过；PostgreSQL 双 Manager 并发停用测试已加入，当前 SQLite 因不支持 `select_for_update()` 明确跳过；Ruff 检查通过。

### BoardMembership 生命周期 M2

- 新增 Devenir `/dashboard/memberships/`：支持搜索/筛选、直接授予、角色调整、停用、恢复及 Manager 原子交接；Django 默认 Membership CRUD 与批量写继续关闭。
- 新增独立 `boards.manage_all_board_memberships` Permission；入口要求 dashboard 身份和有效 privileged Session，每次写操作再校验新鲜 TOTP，capability 绑定用户、Session、动作与目标并只能消费一次。
- pending 申请冲突、非法状态、inactive 目标、superuser Membership 与最后一名 Manager 停用均 fail closed；所有成功动作写入关系型事件并在提交后镜像 Mongo HMAC。
- 修正 dashboard 用户无法绑定 TOTP 的资格矛盾；39 项既有 Membership/申请回归、22 项 M2/MFA 定向测试、迁移漂移与 Ruff 检查通过。事件详情和全验证 super_admin break-glass 留待 M3。

### BoardMembership 生命周期 M1

- 新增 append-only `BoardMembershipEvent`、Membership `updated_at` 和迁移；事件保存角色/active 前后状态、来源、原因、关联申请及 Board/User/actor 快照。
- 申请批准与成员自助退出改用统一事务状态内核；Membership 和关系型事件同事务提交，pending 冲突、空操作及 inactive 目标 fail closed，提交后再镜像 Mongo HMAC。
- super_admin 增加事件只读观察入口，默认 Membership CRUD 仍关闭；当时 Devenir Dashboard、独立 Permission、TOTP step-up 与全验证 break-glass 留待后续阶段。
- 39 项 Membership/申请定向测试、迁移漂移检查与 Ruff 静态检查通过。

### Stage 7 手工验收修正

- superuser 与显式 `dashboard_user` 纳入最新登录唯一策略；新浏览器成功登录后，旧浏览器 Session 在下一请求失效，普通账号仍允许多设备使用。
- 板块权限申请页增加当前有效 Membership；安全运维页增加本页全选与清除；顶部导航恢复常驻“新文章”主按钮。
- `/review/` 改用 Reviewer/Manager 审核能力判定，VerifiedUsers 与 Contributor 不再因投稿能力进入审核中心。
- 板块权限页补齐成员退出闭环：短时邮箱验证后停用本人非 Manager Membership，保留审批历史并记录 Mongo+HMAC 审计；Manager 与存在待审核申请的成员不能自助退出。

## [2026-08-02]

### SiteOperators 独立安全运维入口

- 新增 `/operations/security/`，按查看与运行审计两个 Permission 分离授权，SiteOperators 不再进入 `/dashboard/`。
- 页面只读展示日志完整性状态、筛选和分页；单次核验限制在选中记录，服务层事务加锁并记录新的 HMAC 审计事件。
- SecureLogEntry 从自定义 Dashboard 移除；修改、补签和删除仍不向 SiteOperators 开放。
- `/dashboard/` 新增模型注册 fail-fast 白名单；Group Permission、`is_staff` 与 Board Manager Membership 即使叠加，也不能获得工作台外壳入口。

## [2026-07-29]

### Stage 7 审核入口收敛

- 新增 `/review/` 统一审核中心，汇总账号、板块权限、稿件与评论审核；业务授权继续由全局 Permission、Board Policy 和既有事务 Service 裁决。
- `/dashboard/` 收紧为 active `dashboard_user` 或 superuser，UserManagers、SiteOperators 与 Board Manager 不再因 Group/Membership 自动获得 AdminSite 外壳。
- `dashboard_user` 纳入 MFA 强制对象；MyUser、BoardAccessRequest、Comment 的业务审核入口移出 Dashboard，避免形成第二套状态修改路径。
- UserManager 只能启停非 staff、非 dashboard、非 superuser 普通账号，且不能绕过尚未完成的邮箱邀请；Board Manager 继续只能审批所属板块可授予角色。
- 明确 Board Manager 是 `BoardMembership.role` 而非 Django Group，用户编辑页不显示该组属于正确行为。

### Git 与多 Agent 交接治理

- 固化“先向用户确认，再由主 Agent 从已提交 SHA 创建新的 `codex/<task>` 分支和独立 worktree”；接收 Agent 不得操作 branch/ref/worktree 生命周期。
- 针对 `refs/heads/codex/` 丢失事件补充 ref/worktree 快照、分步创建、全量核验、立即停手和 reflog 恢复规范；本地执行手册与 WorkBuddy memory 均保持 git-ignored。

### Devenir 投稿与审核体验修复

- Board 权限申请成功后显示一次性的 Devenir 中央确认层，明确提示等待审核或主动联系管理员，申请历史仍在原页更新。
- Board 权限申请提交前强制短时邮箱验证：复用 accounts purpose 隔离的验证码、冷却、小时上限和失败锁定；改密凭据不可互用，申请成功立即消费 10 分钟 grant；40 项相关定向契约与 Ruff 检查通过。
- 评论表单移除匿名昵称输入，服务端从登录账号 Profile/username 确定作者并忽略伪造 nickname；未登录用户只显示登录入口。
- 新增 `/Blogs/review/` Board-scoped 稿件流程页，按有效状态展示提审、通过、驳回和下架操作；Admin 分开报告无权限与状态不匹配。
- “PUBLISHED / 可下架”增加 Board、Tag、作者和标题/摘要组合筛选；以每批 8 篇的签名游标进行 htmx 懒加载，片段请求不执行顶层分页 COUNT 或重查其他状态栏；新增 `status/created_time/id` 复合索引支撑顺序读取。
- 修复窄桌面切换汉堡导航后 Hero 仍保留 `100vh` 造成的大面积顶部空白；本轮 53 项定向回归与 Ruff 检查通过。

### accounts_linear Stage 7（观察期开始）

- 移除 `is_reviewer` 的 Admin 展示/分配入口、superuser 默认赋值和 Board 测试账号写入；旧旗标不再形成新的运行时状态。
- 增加旧旗标无授权效果的回归测试；字段与模型层防篡改保护暂留一个发布周期，删除迁移归入 Stage 8。
- 新服务器日常运维入口确定为 Tailscale + 非 root SSH key + 按需 `sudo`；TLS 1.3 mTLS、密码与 TOTP 继续保护应用管理面。
- 记录后续 Board 缺口；其中申请前短时邮箱验证已于同日后续补丁完成，尚余 Index 文章流、Skate Clip 的 1 竖 3 横比例契约，以及按 Board Policy 隔离的内容管理工作区。
- 修复登录后窄桌面窗口的 Devenir 顶栏挤压：宽度不足时提前切换侧边抽屉，并禁止导航标签逐字换行。

### H3 生产传输路线冻结
- 生产 `/super_admin/` 固定为 Nginx TLS 1.3 mTLS；应用解析、证书绑定命令与 readiness 仅接受 `standard-tls`
- `sm2-tlcp` 仅保留为隔离实验元数据，不接生产认证链、不计入 H3 发布验收；新增不含任何真实密钥的 Nginx 配置评审模板
- 整理 `accounts` 结构：TOTP、mTLS 与特权 Session 归入 `accounts/authn/`，测试归入 `accounts/tests/`
- H3d 增加默认忽略生成物的 Client CA/OpenSSL 模板及签发、CRL、轮换、泄露处置和 break-glass 手册；readiness 必须显式确认全部真实演练
- 按项目持续维护策略选择 OpenSSL 4.0.x 最新补丁版作为 H3 边界基线（初始 4.0.1）；新增 Nginx 实际链接、CA CLI 版本与配置语法检查脚本
- OpenSSL 4.0.1 开发 CA 生命周期实测通过：clientAuth 叶证书、链验证、PKCS#12、吊销与 CRL error 23 拒绝；测试密钥仅保留在被忽略的 `.local` 目录
- H3 安全检查点通过 Ruff、迁移一致性检查及全项目 250 项测试；MFA/mTLS 生产强制开关仍默认关闭

## [2026-07-28]

### 后台加固 H3 应用侧 mTLS
- 新增多证书 `ClientCertificateBinding`：issuer 使用 SM3 摘要索引，保存 serial/Subject/profile/有效期/状态/认证版本，不保存证书 PEM 或私钥
- 固定独立管理 Host、可信代理网络/Unix socket、仓库外代理共享认证值与 `X-PA-mTLS-*` Header 契约；错误 Host、来源、验证结果、profile、Subject、账号绑定一律 fail closed
- `/super_admin/` 串联客户端证书、密码与 RFC 6238 TOTP；privileged Session 绑定证书 ID/版本，证书过期、撤销或更换时立即要求重新认证
- 增加证书绑定/撤销/readiness 命令和只读 Admin 观察入口；事件继续由 `LogEntry → SecureLogEntry` 进行 SM3-HMAC 完整性保护
- 明确服务器证书继续用 Let’s Encrypt，客户端证书由离线私有 CA 签发；`standard-tls` 与 `sm2-tlcp` profile 不得静默混用，真实 Nginx/TLCP 与 Android 互操作仍待人工验收
- H3 聚焦测试 11 项及 H2/H3/账号/双后台联合安全回归 87 项通过；MFA 与 mTLS 生产开关保持默认关闭

### 后台加固 H2 完成
- 新增 Devenir 风格 TOTP 绑定、确认、恢复码一次性展示与登录 challenge 页面；QR 由 `qrcode==8.2` 在内存生成，敏感响应统一 `no-store`
- 强制账号密码通过后只创建 5 分钟 pending challenge；新 TOTP 时间步成功后才登录并签发 15 分钟 privileged Session，同一步重放拒绝
- 失败按账号及账号+IP在共享缓存计数，第 5 次进入 15 分钟冷却；恢复码只进入受限重绑状态，过期时直接注销
- `/dashboard/` 与 `/super_admin/` 由 middleware 统一保护，原生 Admin 登录在强制模式下转到账号登录；普通非特权账号保持单阶段登录
- 新增 fail-closed `check_mfa_readiness` 上线前置检查和开关回滚流程；`MFA_ENFORCEMENT_ENABLED` 默认关闭，真实设备/break-glass 演练完成前不得开启
- H2、账号登录与双后台相关回归 76 项通过；按任务约束未运行 K3/back 覆盖的全项目测试

### 后台加固 H2a-2/3 绑定与恢复服务
- 新增 fail-closed 版本化 MFA keyring 配置、10 分钟 pending TOTP 绑定、首次验证码确认和一次性 provisioning URI 返回；仅 active superuser 与 active Board Manager 可为自己绑定
- 新增 `MfaRecoveryCode` hash-only 模型与迁移，首次确认生成 10 枚高熵恢复码；条件更新保证单码竞争消费最多成功一次，消费本身不创建登录 Session
- superuser 重置执行权限复核，自助重置额外校验当前密码；撤销/过期覆盖 seed 密文、删除恢复码并递增 `auth_version`
- 所有成功及验证失败只把固定事件/原因码写入 Django `LogEntry`，并要求同步生成 HMAC `SecureLogEntry`；未记录 seed、URI、验证码、恢复码或任意撤销原因文本
- H2a 服务定向测试通过；随后由“后台加固 H2 完成”接入 UI 与 H2b 登录状态机

### Board Index 合并前加固
- 修复音乐 Snapshot/Entry 扁平化迁移：在删除旧表前双向搬运 Apple/Spotify 全字段与时间元数据，并新增 `0007 → 0008 → 0007` 往返迁移测试
- 通过抽象模型基类在 `clean()` 与 `save()` 层强制 Skateboard、Music、Coding 内容归属固定 Board，拒绝 ORM/脚本写入错误板块
- 首页只展示已有独立 Index 模板的 active Board，避免新增板块入口指向 404；Admin Glitch 颜色预览改用 Django 5.2 `format_html()`
- 移除 PyPI 不存在且代码未使用的 `self==2020.12.3`，恢复 Python 3.13.5 + Django 5.2.16 的全量依赖安装
- Django system check、迁移漂移检查、Ruff、20 项聚焦测试、100 项 Board/全局角色回归与 215 项全项目测试通过（16 项未来 MFA 契约按设计跳过）

## [2026-07-27]

### 后台加固 H2a-1 设备模型
- 新增 encrypted-only `MfaTotpDevice` 与迁移：单用户只允许一个逻辑设备，不保存 seed 明文或 `otpauth://` URI，也不注册到 Django Admin
- 密文通过 AAD 绑定 user ID 与预生成 device UUID；数据库约束 `pending/active/revoked` 时间戳、`auth_version >= 1` 和非负防重放时间步
- 新增 7 个 ORM/数据库测试；当前仍未开放绑定页面、生成业务 seed 或修改登录链路

### 后台加固 H2a-0 加密边界
- 固定 `PyOTP==2.10.0` 与 `cryptography==49.0.0`，不自行实现 TOTP、Base32 或密码算法
- 新增无持久化的 AES-256-GCM seed 加密边界，使用版本化 key ID、每次随机 96-bit nonce 与调用者提供的设备 AAD
- 非法 keyring、未知 key、密文或 AAD 篡改均默认拒绝，错误消息不包含 key、seed、nonce 或密文
- 新增 5 个可执行加密测试；设备/恢复与登录的 16 个契约测试继续跳过，未创建模型、迁移或业务 seed

### 后台加固 H2 设计冻结
- 将 TOTP 拆分为 H2a 绑定/恢复与 H2b 登录强制，禁止首次引入密钥模型时同步改造登录链路
- 冻结加密 seed、版本化 KEK、恢复码 hash、防重放时间步、`auth_version` 与 15 分钟特权 Session 契约
- 明确 H2a 观察和 break-glass 演练是 H2b 强制登录的进入条件，不允许未绑定时密码降级直通
- 新增跳过状态的 H2 安全测试骨架；当前未引入 TOTP 依赖、未生成或保存 seed、未修改登录运行时

### 后台加固 H1 / Stage 6b
- 新增 `BoardAccessRequest`、`/boards/access/` 申请入口与只读审核记录，VerifiedUsers 可申请但不会在提交时直接获得 Board CRUD
- Board Manager 只可审核自己板块的 Contributor、Editor、Reviewer；禁止跨板块、自审、授予 Manager、恢复停用权限和变更已有 Manager
- 审批 Service 使用事务与行锁创建或更新唯一 `BoardMembership`，拒绝重复处理，并在提交后写 MongoDB HMAC 审计记录
- Manager Membership 可进入工作台并只见本板块申请，不获得账号管理、安全审计或全局 Group 权限
- 新增 16 项申请、审批、越权、回滚与入口测试；全量 179 项测试、迁移漂移检查、Django system check 与 Ruff 通过

### 后台加固 H0
- 使用项目自定义 `SuperuserAdminSite` 作为默认 Django AdminSite，`/super_admin/` 从 active staff 收紧为 active superuser
- 系统后台登录表单在认证阶段拒绝 staff-only 与 dashboard-only 账号，不为其建立后台 Session
- 新增双后台入口矩阵测试，覆盖匿名、普通账号、dashboard、staff-only、active superuser 和 inactive superuser；全量 157 项测试与 Ruff 通过

### 后台加固 H1 / Stage 6a
- 新增 `boards.apply_board_access`、`accounts.manage_user_accounts`、`security.view_audit_log` 与 `security.run_integrity_audit` 自定义 Permission
- 幂等初始化 VerifiedUsers、UserManagers、SiteOperators；active 旧账号迁入 VerifiedUsers，active 非 superuser staff 收敛到 UserManagers
- UserManagers 仅可启停非 superuser 账号；SiteOperators 仅可查看和运行日志完整性审计；全局 Group 不授予任何 Board CRUD
- 首次迁移、幂等初始化、Group 运行时入口与拒绝路径均有测试；全量 163 项测试与 Ruff 通过

### 博客基础 F3
- 新增 `/Blogs/archive/` 公开年月归档，复用 Devenir Post Stream 卡片并提供月份快速索引
- 新增 `/feed/` RSS 与 `/feed/atom/` Atom，只输出公开已发布文章和固定公网基址的绝对链接
- Profile、归档和 Feed 共用 `Post.publicly_visible_posts()`，防止草稿、审核中及内部文章泄漏
- 邮箱验证码发送页增加服务端截止时间驱动的重发冷却与验证码有效期倒计时
- `run.py` 增加单实例锁、旧进程自动替换与退出清理，适配 PyCharm 重新运行
- Ruff 与 143 项全量测试通过

### 博客基础 F4
- 全局模板增加 description、canonical、Open Graph 与 RSS/Atom 自动发现；Footer 收敛为单个 Feed 入口
- 文章详情输出固定公网基址的 Article 元数据，非公开状态使用 `noindex, nofollow`
- 新增 `/robots.txt`，屏蔽后台、邀请、账号设置、上传和 API，并指向绝对 Sitemap URL
- Sitemap 切换统一公开文章 QuerySet，修复内部文章泄漏风险和旧版 location 路由
- 接入 Devenir 生产 404/500 handler，错误响应不包含异常或 Traceback
- 清理 7 个既有未使用导入/变量；全仓 Ruff 与 149 项全量测试通过

### 博客基础 F5
- 按 RFC 9116 新增 `/.well-known/security.txt`，发布安全联系邮箱、180 天有效期、中/英/日语言偏好与固定 Canonical
- 新增权重 84 的生产上线检查清单，覆盖环境、迁移、静态文件、冒烟、权限、审计和回滚
- `SECURITY_CONTACT_EMAIL` 支持环境变量覆盖；全仓 Ruff 与 150 项全量测试通过

### 并行开发与文档治理
- 新增权重 95 的 `DOCUMENTATION_GUIDE.md`，保持 `V2GUIDE.md` 为唯一最高权重并固定 Agent 阅读顺序
- 冻结 `codex/admin-hardening` 与 `codex/board-index-k3` 的分支、worktree、所有权和合并边界
- K3 Board Index 的长期前后端边界回写 V2 与 boards 文档；临时交接文件不再作为仓库文档
- HANDOFF 与同类 Agent 临时材料统一改为本地未跟踪文件；推荐存入 `.local/handoffs/`，长期结论必须提升到正式 Guide/DEVELOPMENT/V2 文档

## [2026-07-26]

### 邮箱验证改密与博客基础 F2
- 修改密码前增加当前 Session 绑定的 6 位邮箱验证码，仍保留旧密码与 Django 新密码策略校验
- 验证码默认 10 分钟有效、60 秒重发冷却、每小时最多 3 封、每枚最多错误 5 次；改密授权 10 分钟后失效并在成功后消费
- 新增公开 About 与隐私说明页面，记录账号、评论、Session、IP 限流、应用日志和 MongoDB HMAC 审计的用途与保留方式
- 桌面/移动导航增加 About，Footer 增加 About 与隐私入口；完成 390px 响应式检查
- Profile 的“修改密码”固定开启新邮箱验证，不复用此前的短时授权；已验证表单刷新仍可继续填写
- 修改密码页升级为 Credential Rotation Console：步骤轨、授权倒计时、密码熵信号、规则节点、匹配状态及提交扫描动画

### 作者 Profile 与账号设置
- 新增默认私密的 `UserProfile`，支持展示名、简介、头像、个人网站、GitHub 与所在地
- 新增本人 Profile 跳转、公开作者页、资料编辑和安全密码修改；修改密码后保留当前会话
- 公开作者页与文章作者链接仅暴露 active 且主动公开的资料，并统一过滤公开已发布文章
- 头像复用安全图片校验与随机文件名；Devenir 页面完成桌面及 390px 响应式检查
- 修复保留已有头像时 `ImageFieldFile` 缺少 `content_type` 导致资料提交 500；新上传图片仍执行完整内容校验
- Profile 的 LOC/WEB/GIT 从按钮式徽章调整为 Devenir 身份坐标轨

### 博客基础体验规划
- 新增权重 87 的 `BLOG_FOUNDATION_GUIDE.md`，建立 `blog_foundation_linear` F0–F5
- 冻结 Profile、密码修改、About/隐私、归档/Feed、SEO/robots 与错误页的 App 边界和验收标准
- 明确不开放公共注册，不引入关注、点赞、私信、排行榜或通用联系表单
- 纠正 Blogs 文档将尚不存在的 `feed.py` 误写为当前组件的问题

### 邀请制账号激活
- 个人站保持关闭公共注册，由 superuser 通过 Admin 发放用户名和邮箱
- 新账号没有可用密码且默认未激活；受邀者通过限时、单次邮件链接自行设置密码
- 邀请只保存 Token 哈希，重发即撤销旧链接；邮件在数据库提交成功后发送
- 激活时原子启用账号并加入 `VerifiedUsers`，Stage 6a 后续再为该组绑定固定全局 Permission
- 生产设置增加固定公网基址与 SMTP 环境变量，开发环境保留 Console Email Backend

## [2026-07-21]

### 文档目录整理
- 根目录保留项目入口、全局开发说明与最高权重 V2 路线，专项指南归档到 `docs/guides/`
- 新增 `docs/README.md` 文档索引，并同步更新全局与各 App 的指南引用
- `GITGUIDE.md` 继续作为不进入版本控制的本地规范保存

## [2026-07-19]

### 本地权限手测账号与后台入口
- 新增仅限 `DEBUG=True` 的幂等命令，为指定 Board 创建 Contributor、Editor、Reviewer、Manager 及无 Membership 拒绝样本账号
- 角色样本只持有 Dashboard 入口和单一有效 BoardMembership，不授予 staff、superuser、Group 或直接用户权限
- Devenir 全局 Header 与移动 Sidebar 增加“工作台”；superuser 同时显示独立的“系统后台”入口
- 增加命令安全护栏、幂等角色矩阵和双入口渲染契约测试
- 工作台中的账号管理模块在 Stage 6 `UserManagers` 落地前收紧为仅 superuser，避免 Board 角色凭入口旗标启停全站用户
- 修复暗色 Admin 的 Group/Permission 双选框白底白字，并统一历史 superuser 的工作台显示与后端入口判定
- `/dashboard/` 使用独立登录表单，不再错误要求 Board 工作台用户具有 `is_staff`；`/super_admin/` 仍保持 Django staff 校验
- Jazzmin 侧栏、登录页和站点图标切换到最新 `PowerAdapter_icon.webp` / `PowerAdapter_logo.webp`

### PostgreSQL 日志完整性热修
- `SecureLogEntry` 使用带版本号的规范 JSON 载荷，消除 Admin 创建前后 `object_id` 整数/字符串漂移导致的误报
- 默认 HMAC 初始化改为只补缺，不再覆盖已有审计证据；新增 `--repair-known` 安全升级已验证旧签名
- 无法由旧版管道格式或 JSON-v2 算法验证的记录保持可疑，不被批量重签洗白
- 新增 8 个日志完整性回归测试；已完成的实现细节从 `V2GUIDE.md` 下移到 `security/DEVELOPMENT.md`

### Accounts / Boards 业务边界
- accounts 负责 MyUser、认证、账号状态、MFA 规划和全局 Group 编排，不拥有 Board 角色或对象 Policy
- boards 负责 Board、BoardMembership、角色规则、跨 App Policy，以及后续 BoardAccessRequest 和审批服务
- Blogs、comment、security 各自拥有模型和 Permission 定义；Board 范围操作统一调用 boards Policy
- `accounts_linear` 名称为交接兼容继续保留，阶段 6 拆分为 accounts 全局身份迁移与 boards 申请审批两部分

### accounts_linear Stage 4
- BoardAdmin 仅向本 Board Manager 开放运营字段，slug/category/is_active 与结构操作继续由 superuser 独占
- Post/PostRevision Admin 按 BoardMembership、作者和角色过滤；Category 表单及 autocomplete 同步收敛，Manager 编辑不再覆盖文章作者
- Dashboard Comment 队列仅向所属 Board Reviewer/Manager 只读展示；批量审核与其他状态 action 留到 Stage 5 接入逐对象 Policy
- 新增 8 个 Admin 隔离测试，覆盖跨 Board 直接 URL 拒绝；完整测试集从 48 增至 56 并全部通过，system check 为 0

### accounts_linear Stage 5
- 新增事务化 Post 工作流 Service，提交/通过/驳回/下架逐对象加锁并重检 Board Policy；Admin 不再批量直写状态
- Dashboard 评论 action 按 Reviewer/Manager Board Scope 恢复，继续写入 MongoDB HMAC 审计；跨 Board queryset 中的评论会被跳过
- 前台写作、Category 表单、图片上传、STAFF_ONLY、修订端点和评论提交统一调用 Board Policy；新建强制草稿，编辑已提交/发布内容退回草稿
- Devenir 新建/编辑按钮按 Policy 渲染；移除 Category 页面跨用户片段缓存，避免内部文章 HTML 缓存泄露
- Post/Category DRF API 改为 Policy-scoped 只读 ViewSet，修复重复 namespace；所有写方法返回 405
- 新增 9 个 Stage 5/action 测试；完整测试集由 56 增至 65 并全部通过，Ruff 与 system check 为 0

### accounts_linear Stage 3
- 新增 `boards/policies.py`，统一解析 Post/Comment 的 Board 归属并适配 BoardMembership 角色规则
- 未映射或重复 Category→Board 映射默认拒绝；停用用户、Board、Membership 和跨 Board 操作均拒绝
- 固定 Contributor 仅提交本人文章、Reviewer/Manager 禁止自审、直接 Django Permission 不扩大 Board Scope
- BoardAdmin 新增和删除收紧为仅激活 superuser；现有 Board 修改范围将在 Stage 4 接入
- 新增 12 个 Admin/Policy 测试，完整测试集由 28 增至 40 并全部通过

### Board 权限边界澄清
- Django Group 仅承载邮箱验证、账号管理和全站审计等全局职责；Board 角色只存入 `BoardMembership`
- Board 作为跨 App 授权边界，通过 Category 控制 Blogs.Post，并通过 Post 延伸到 comment.Comment
- 取消 `BoardCreators` 设计；新增和删除 Board 仅限 superuser，因为新板块意味着新的前端代码与部署

### Comment 开发库迁移修复
- `comment.0003_comment_user` 在新增非空 `user_id` 前显式删除无法归属的旧评论，避免 SQLite 表重建触发 `NOT NULL` 错误
- 开发数据库迁移已成功应用，修复前端读取评论时的 `no such column: comment_comment.user_id`

## [2026-07-13]

### accounts_linear Stage 2
- 新增 `boards.BoardMembership`，固化 Contributor / Editor / Reviewer / Manager 单角色模型
- 增加 `unique_board_member` 约束，同一用户在同一 Board 只保留一条可更新或停用的成员记录
- 在 `/super_admin/` 增加仅 superuser 可见的完全只读成员观察入口，暂不向 dashboard 暴露跨 Board 数据
- 新增 5 个 ORM/Admin 边界测试；完整 Django 测试集增加至 28 个并全部通过

### 文档权重体系
- 为 28 份项目自有 Markdown 增加 `0–100` 文档权重，`V2GUIDE.md` 设为最高权重 `100`
- 新增 `docs/guides/DOCUMENTATION_GUIDE.md`，定义 Agent 阅读顺序、作用域补充和冲突裁决规则
- 旧文档保留为历史基线，但不得覆盖更高权重的新架构、安全和版本决策

## [2026-07-12]

### 安全、滥用防护与审计链收口
- `hot_posts` 公开/内部缓存隔离，公开榜单排除 STAFF_ONLY
- 登录失败按用户名+IP 哈希计数，默认 5 次锁定 15 分钟
- Comment 强制关联用户，增加每用户+IP 限流和作者软删除
- CommentAdmin 审核 action 统一进入 `moderate_comment → MongoLogger → SM3-HMAC`
- 增加 `security.0003_delete_commenteventlog`，移除已迁往 MongoDB 的旧 ORM 模型
- 自动化测试由 1 个增加到 10 个
- 优化 `.codebuddy/skills` 四个 Skill，修复乱码、精简流程并删除空占位资源

### 图片上传与生产配置加固
- 正文图片上传移除 `csrf_exempt`，要求 dashboard 身份并执行 CSRF 校验
- 正文图片和文章封面统一校验 5MB 上限、MIME、真实图片格式与像素总量
- STAFF_ONLY 修订正文/diff 端点补齐 404 权限边界，前台写作入口对齐 dashboard 角色
- production settings 对 SECRET_KEY、ALLOWED_HOSTS、HMAC key 显式校验，统一环境变量拼写
- `requirements.txt` 从 UTF-16 规范化为 UTF-8，显式声明 Pillow 与 python-dotenv
- 修复 DRF `PostSerializer.tags` 的 M2M source，`check --deploy` Schema 警告清零
- 移除运行路径遗留 `print()` 与评论提交调试输出
- 自动化测试增加至 16 个

## [2026-06-22]

### 全项目日志代码补全
- 各 App 补充完整日志调用（INFO/WARNING/ERROR），覆盖 15 个文件，0 lint 错误
- **Blogs**: views（PostCreate/PostEdit/PostDetail.handle_visit/post_img_upload/clear_page_caches）、apis（perform_create/update/destroy）、管理命令
- **Comment**: views（提交/审核）、middleware（IP 提取异常处理）、admin（3 个审核 actions）、管理命令
- **Security**: signals（同步失败）、mongo_client（连接确认）、管理命令
- **Accounts**: LoginView（登录成功 INFO + 失败 WARNING，区分 account_inactive/invalid_password）
- **Config**: LinkAdmin/SideBarAdmin（save_model/delete_model）

### Kaomoji 日志格式文档化
- 日志格式定义于 `PowerAdapterBlogs/settings/base.py:185-187`：
  - INFO `(✿◕‿◕)` / WARN `(ಠ_ಠ)` / ERROR `(╯°□°）╯︵ ┻━┻`
- `docs/guides/LOGGUIDE.md` v1.0 → v1.1，在多个章节加入 kaomoji 格式说明

### music App 卸载
- 从 `INSTALLED_APPS` 移除 `"music"`（空壳待开发）

### 日志 Admin 权限加固
- `LogEntryAdmin`: 补 `action_time` 到列表列；权限 view→staff, change/delete→superuser only
- `SecureLogEntryAdmin`: 权限 view→staff, change/delete→superuser only
- 普通运维可查看 + 执行审计 action，但不可修改/删除日志

### 修复 superuser 无法管理用户
- `accounts/admin.py` `MyUserAdmin`: 移除 `readonly_fields`（锁死了 username/email/is_active/is_superuser 等字段）
- 恢复后 Django `UserAdmin` 自带权限体系正常生效

### 修复 dashboard_user 无法访问后台 + 登录跳转
- `PowerAdapterBlogs/cus_site.py`: `CustomSite.has_permission()` 重写，检查 `is_active and is_dashboard_user`（原继承 Django 默认 `is_staff` 检查，`is_dashboard_user` 字段从创建以来从未生效）
- `accounts/views.py`: `LoginView.get_success_url()` → dashboard 用户登录后自动跳转 `/dashboard/`
- 两个后台入口权限完全分离：`/super_admin/` 需要 `is_staff`，`/dashboard/` 需要 `is_dashboard_user`

### 修复登录 NoReverseMatch
- **现象**：登录时 `NoReverseMatch: Reverse for 'dashboard' not found`
- **尝试1**：`reverse_lazy("dashboard")` → `reverse("dashboard")`（无效，问题不在 lazy vs immediate）
- **根因**：`AdminSite.urls` 返回的是 include tuple `(urlpatterns, 'admin', 'cus_admin')`，不是普通 view 函数。include 产生的 `URLResolver` 不注册外层 `path(name="dashboard")` 为可 reverse 目标，必须通过 `namespace:子pattern名称` 反解
- **修复**：`reverse("dashboard")` → `reverse("cus_admin:index")`，与默认 `reverse("admin:index")` 同理
- 同步更新 `DEVELOPMENT.md` 路由表，补充 AdminSite URL 反向解析说明

### 纵深防御：模型层权限保护 (S1+S2)
- **S1 防提权**：`MyUser.save()` 非 superuser 回滚 `is_superuser/is_staff/is_dashboard_user`；`MyUserAdmin.save_related()` 非 superuser 跳过 M2M 保存
- **S2 防日志篡改**：`security/signals.py` pre_save/pre_delete 信号拦截 LogEntry/SecureLogEntry
- 基础设施：`accounts/thread_local.py` + `accounts/middleware.py` `RequestUserMiddleware`
- 4 层防御：Admin UI 守卫 → save_related M2M 拦截 → Model.save() 字段回滚 → pre_save/pre_delete 信号

### 项目文档体系建立
- 创建 `accounts/DEVELOPMENT.md`：三旗权限模型、登录流程、Admin 权限流、4 层纵深防御架构、thread-local 基础设施
- 创建根目录 `DEVELOPMENT.md`：项目结构树、完整路由表（按类别分组）、权限模型、中间件链、技术栈、常见问题排查

### 修复 dashboard 用户页面空白 + 不可见数据 + 可改 superuser is_active
- **现象**：dashboard 用户登录后侧边栏有显示，但所有模型列表为空；且可修改 superuser 的 is_active 字段
- **根因1（数据不可见）**：`BaseOwnerAdmin.get_queryset()` 按 `owner=request.user` 过滤，新用户无记录
- **根因2（列表空白）**：每个 ModelAdmin 的 `has_module_permission/has_view_permission` 仍检查 `is_staff`（Django 默认），dashboard 用户 `is_staff=False`
- **根因3（可改超管）**：权限检查只检查了 `request.user`，未检查被编辑目标 `obj` 是否 superuser
- **修复**：
  - `base_admin.py`：新增 `DashboardAdminMixin`（6 个权限方法 + `get_queryset()` 全部切换到 `is_dashboard_user`，跳过 owner 过滤）
  - 应用到 6 个 Admin 类：Category/Tag/Post/LogEntry/SecureLogEntry/CusMyUserAdmin
  - `CusMyUserAdmin.has_change_permission(obj=...)`：目标为 superuser 且请求者非 superuser → 拒绝编辑
  - `CusMyUserAdmin.get_readonly_fields(obj=...)`：同上条件 → 全字段只读（双重保险）
- **权限矩阵**：dashboard 用户 → 查看全量数据/修改文章/审核用户(is_active)，不可改删日志/不可新增删除用户/不可动 superuser

## [2026-06-21]

### P0 修复：MongoDB 日志完整性
- Issue A: `mongo_client.py` 集合命名修复 `self.db[COLLECTION]`；`purge_old_comment_logs.py` 同步修复
- Issue B: `MongoLogger` 新增 `verify_log()` + `audit_all()`；`audit_log_integrity` 新增 `--mongo` 选项
- Issue C: `develop.py` 优先从 `LOGINTEGRITY_HMAC_KEY_BASE64` env 读取，硬编码兜底
- Issue D: `SecureLogEntry.compose_message()` 改用 `json.dumps()` 消除 `|` 冲突；`init_log_hmac` 新增 `--force` 重建
- 架构加固：MongoLogger 连接容错、moderate_comment 异常包裹、cel_model 连接检查
- `requirements.txt` 新增 `pymongo==4.10.1`
- MongoDB 验证通过：写入→HMAC验证→审计→清理全链路 PASS

### Security 模块开发文档
- 创建 `security/DEVELOPMENT.md`，包含架构总览、4 个序列图、4 个已知问题诊断、配置参考、ER 图

### 日志规范文档体系
- 创建 7 个 `LOGGUIDE.md`（全局指南现位于 `docs/guides/`，其余位于各 App）
- 核心设计：应用日志（logger）与审计日志（SecureLogEntry/MongoDB-HMAC）双轨分明

### V2 需求分析
- 与用户讨论 V2 优先级，核心决策：
  - 文章修订追踪 → 轻量嵌入式组件（非独立页面）
  - 版本号 → 文章 SemVer: `v{major}.{minor}`
  - 节点图 Phase 1 → 纯 CSS timeline
- `V2GUIDE.md` 完全重写，包含精化后的数据模型、API 设计、实施步骤

---

## [2025-02-22]

- 修复 TemplatesDoesNotExist Error
- 修改 `db.sqlite3` 位置，由 Django 项目地址更改为根目录
- 完成视图的初步设计及部分 HTML
