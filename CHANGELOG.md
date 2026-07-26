# CHANGE LOG

> **文档权重**：60（历史变更记录；不覆盖当前架构文档）

## [2026-07-27]

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
