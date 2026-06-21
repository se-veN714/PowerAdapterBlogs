# CHANGE LOG

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
- `LOGGUIDE.md` v1.0 → v1.1，在多个章节加入 kaomoji 格式说明

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
- 创建 7 个 `LOGGUIDE.md`（根目录 + 5 个 App + music）
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
