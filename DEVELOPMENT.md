# PowerAdapterBlogs — 项目开发文档

> **文档权重**：82（项目结构与通用开发入口）
> **项目**: 基于 Django 5.2 的个人博客系统  
> **作者**: seveN1foR / PowerAdapter  
> **许可证**: MIT  
> **最后更新**: 2026-07-27 — 完成 blog_foundation_linear F5 security.txt 与上线检查清单

---

## 1. 项目结构

```
DjangoProject/                 # 项目根目录
├── PowerAdapterBlogs/         # Django 项目配置
│   ├── settings/              # 多环境 settings
│   ├── urls.py                # 根路由（⭐ 路由排查入口）
│   ├── cus_site.py            # 自定义 AdminSite（dashboard 后台）
│   └── wsgi.py
├── accounts/                  # 自定义用户模块
├── Blogs/                     # 博客核心（文章/分类/标签/API）
├── comment/                   # 评论模块
├── config/                    # 站点配置（友链/侧边栏）
├── security/                  # 日志完整性（HMAC + MongoDB 审计）
├── themes/                    # 前端模板（bulma 主题）
├── static/                    # 静态资源
├── requirements.txt           # 依赖清单
├── manage.py                  # Django 管理入口
├── setup.py                   # 打包配置
└── CHANGELOG.md               # 变更日志
```

### App 职责速查

| App | 职责 | 开发文档 |
|-----|------|---------|
| `accounts` | 用户模型、登录/登出、权限体系、纵深防御 | `accounts/DEVELOPMENT.md` |
| `Blogs` | 文章 CRUD、分类/标签、全文搜索、REST API | `Blogs/LOGGUIDE.md` |
| `comment` | 评论提交/审核、IP 提取 | `comment/LOGGUIDE.md` |
| `config` | 友链管理、侧边栏配置 | `config/LOGGUIDE.md` |
| `security` | SM3-HMAC 日志签名、MongoDB 审计 | `security/DEVELOPMENT.md` |

---

## 2. 路由总览

**根路由文件**: `PowerAdapterBlogs/urls.py`

### 2.1 前端路由（用户可见）

| URL | 视图 | 说明 |
|-----|------|------|
| `/` | `IndexView` | 首页 |
| `/Blogs/category/<id>/` | `CategoryView` | 分类文章列表 |
| `/Blogs/tag/<id>/` | `TagView` | 标签文章列表 |
| `/Blogs/post/` | `PostListView` | 全部文章列表 |
| `/Blogs/post/<slug>` | `PostDetailView` | 文章详情 |
| `/Blogs/post/<slug>/comment/` | `CommentView` | 提交评论 |
| `/Blogs/post/<slug>/edit/` | `PostEditView` | 编辑文章 |
| `/Blogs/post/new/` | `PostCreateView` | 写新文章 |
| `/Blogs/search/` | `SearchView` | 搜索 |
| `/Blogs/img_upload/` | `post_img_upload` | 图片上传 |
| `/links/` | `LinkListView` | 友链页 |
| `/about/` | `AboutView` | 站点定位、内容、Board 与技术说明 |
| `/privacy/` | `PrivacyView` | 数据用途和保留方式说明 |
| `/sitemap.xml/` | sitemaps | 站点地图 (缓存1h) |

### 2.2 后台路由（权限分离）

| URL | 后台 | 权限要求 |
|-----|------|---------|
| `/super_admin/` | Django 原生 Admin | `is_staff = True` |
| `/dashboard/` | 自定义 AdminSite | `is_dashboard_user = True` |
> **反向解析**：AdminSite 的 URL 必须通过 `namespace:name` 形式反向解析，如 `reverse("cus_admin:index")` → `/dashboard/`。`custom_site.name = 'cus_admin'`。

### 2.3 账号路由

| URL | 视图 | 说明 |
|-----|------|------|
| `/accounts/login/` | `LoginView` | 登录（dashboard 用户自动跳转 /dashboard/） |
| `/accounts/logout/` | `LogoutView` | 登出（跳转首页） |
| `/accounts/profile/` | `MyProfileRedirectView` | 登录用户进入自己的 Profile |
| `/accounts/u/<username>/` | `ProfileDetailView` | 公开作者页；私密页仅本人预览 |
| `/accounts/settings/profile/` | `ProfileUpdateView` | 编辑本人公开资料 |
| `/accounts/password/change/` | `AccountPasswordChangeView` | 校验旧密码并保留当前会话 |
| `/accounts/password/change/verify/` | `PasswordEmailVerificationView` | 短时邮箱验证码与发送/错误次数限制 |

### 2.4 API 路由

| URL | 说明 |
|-----|------|
| `/Blogs/api/posts/` | REST 文章列表 (DRF ViewSet) |
| `/Blogs/api/categories/` | REST 分类列表 |
| `/Blogs/api/schema/` | OpenAPI Schema |
| `/Blogs/api/docs/` | Swagger UI |

### 2.5 自动补全

| URL | 说明 |
|-----|------|
| `/category-autocomplete/` | 分类 autocomplete (dal_select2) |
| `/tag-autocomplete/` | 标签 autocomplete (dal_select2) |

### 2.6 DEBUG 专属

| URL | 说明 |
|-----|------|
| `/__debug__/` | Django Debug Toolbar（仅 DEBUG=True） |

---

## 3. 权限模型（三旗分离）

项目使用自定义 `MyUser` (`accounts/models.py`)，三个布尔字段**独立控制、互不干扰**：

| 字段 | 作用 |
|------|------|
| `is_staff` | 访问 `/super_admin/` (Django 原生 Admin) |
| `is_dashboard_user` | 访问 `/dashboard/` (自定义 AdminSite) |
| `is_superuser` | 拥有所有权限（可管理用户、日志等） |

> 权限检查入口：
> - `/super_admin/` → Django 默认 `AdminSite.has_permission()` → `is_staff`
> - `/dashboard/` → `CustomSite.has_permission()` → `is_dashboard_user`
>
> 见 `PowerAdapterBlogs/cus_site.py` 和 `PowerAdapterBlogs/urls.py:31-33`

---

## 4. 中间件链

顺序很重要（`settings/base.py:71-83`）：

| 顺序 | 中间件 | 作用 |
|------|--------|------|
| 1 | `SecurityMiddleware` | 安全头 |
| 2 | `WhiteNoiseMiddleware` | 静态文件 |
| 3 | `SessionMiddleware` | 会话 |
| 4 | `ClientMetaMiddleware` | 提取客户端 IP/UA |
| 5 | `UserIdMiddleware` | 设置 `_user_id` thread-local |
| 6 | `CommonMiddleware` | URL 规范化 |
| 7 | `CsrfViewMiddleware` | CSRF 防护 |
| 8 | `AuthenticationMiddleware` | 用户认证 |
| 9 | `RequestUserMiddleware` | 设置 `_request_user` thread-local |
| 10 | `MessageMiddleware` | Flash 消息 |
| 11 | `XFrameOptionsMiddleware` | 点击劫持防护 |

---

## 5. 技术栈

| 类别 | 技术 |
|------|------|
| 框架 | Django 5.2, DRF 3.16 |
| 数据库 | PostgreSQL + psycopg2-binary |
| 缓存/会话 | Redis (django-redis 6.0) |
| 静态文件 | WhiteNoise 6.12 |
| Admin UI | django-jazzmin 3.0 |
| Autocomplete | django-autocomplete-light 3.12 |
| API 文档 | drf-spectacular 0.28 (Swagger) |
| 日志完整性 | gmssl SM3-HMAC + pymongo MongoDB 审计 |
| 日志格式 | Kaomoji 表情日志 (INFO/WARN/ERROR) |
| 模板 | Bulma CSS + widget_tweaks + mathfilters |
| 开发工具 | django-debug-toolbar, django-extensions, ruff |

---

## 6. 开发文档索引

| 文档 | 内容 |
|------|------|
| `V2GUIDE.md` | 最高权重：当前版本、架构与路线决策 |
| `docs/README.md` | 全项目文档索引 |
| `docs/guides/DOCUMENTATION_GUIDE.md` | 文档权重、阅读顺序与冲突处理规则 |
| `CHANGELOG.md` | 全项目变更日志 |
| `docs/guides/CODING_GUIDE.md` | Python 之禅、Django 分层、Mixin/继承准入条件与 Code Review 清单 |
| `docs/guides/DJANGO_LTS_UPGRADE.md` | Django 5.2 LTS 版本、兼容边界与升级验证 |
| `docs/guides/BLOG_FOUNDATION_GUIDE.md` | Profile、账号设置、About、隐私、归档、Feed 与公开站点元数据路线 |
| `docs/guides/DEPLOYMENT_CHECKLIST.md` | 生产环境变量、部署、冒烟、安全、审计与回滚执行清单 |
| `DOCUMENTATION_GUIDE.md` | 文档权重、Agent 阅读顺序与冲突处理总则 |
| `themes/devenir/BOARD_INDEX_HANDOFF.md` | K3 Board 独立 Index 前端分支边界与后端上下文契约 |
| `docs/guides/LOGGUIDE.md` | 全项目日志主规范 |
| `requirements.txt` | 依赖清单 |
| `accounts/DEVELOPMENT.md` | 用户模块详细架构 |
| `security/DEVELOPMENT.md` | 日志完整性详细架构 |
| `themes/devenir/DEVELOPMENT.md` | 当前 Devenir 主题架构、模板与静态资源说明 |
| `themes/devenir/POSTLIST_HANDOFF.md` | PostList 前端重构规划、K3 修改边界与验收标准 |
| `accounts/LOGGUIDE.md` | accounts 日志规范 |
| `Blogs/LOGGUIDE.md` | Blogs 日志规范 |
| `comment/LOGGUIDE.md` | comment 日志规范 |
| `config/LOGGUIDE.md` | config 日志规范 |
| `security/LOGGUIDE.md` | security 日志规范 |

---

## 7. 快速命令

```bash
# 开发运行
python manage.py runserver

# 检查路由（排查 NoReverseMatch 等）
python manage.py show_urls

# 日志完整性审计（PostgreSQL）
python manage.py audit_log_integrity

# 日志完整性审计（PostgreSQL + MongoDB）
python manage.py audit_log_integrity --mongo

# HMAC 初始化
python manage.py init_log_hmac

# 安全升级能被旧算法验证的历史 HMAC
python manage.py init_log_hmac --repair-known

# 强制重建会覆盖审计证据，仅限完成取证后的人工基线重置
python manage.py init_log_hmac --force
```

---

## 8. 常见问题排查

| 问题 | 排查路径 |
|------|---------|
| 404 / 路由不匹配 | 先查 §2 路由表，再 `python manage.py show_urls` |
| NoReverseMatch | 检查 URL name 拼写和 namespace（见 §2） |
| 登录后无法访问后台 | 确认 `is_staff`/`is_dashboard_user` 是否正确勾选 |
| dashboard 用户看到 403 | 确认 `CustomSite.has_permission()` 逻辑（`cus_site.py`） |
| 静态文件 404 | DEBUG=False 时需要 `python manage.py collectstatic` |
| HMAC 验证失败 | 先运行审计并保留证据；仅对已知历史格式使用 `init_log_hmac --repair-known`，不得直接 `--force` |

### 8.1 生产邮件与邀请账号

生产环境需要配置 `PUBLIC_SITE_URL`、`SECURITY_CONTACT_EMAIL`、`DEFAULT_FROM_EMAIL`、`EMAIL_HOST`、`EMAIL_PORT`、`EMAIL_HOST_USER`、`EMAIL_HOST_PASSWORD`，并按服务商选择 `EMAIL_USE_SSL` 或 `EMAIL_USE_TLS`（不可同时开启）。开发环境默认使用 Console Email Backend，邀请链接会输出到运行终端。

账号发放入口为 `/super_admin/accounts/myuser/add/`：只填写用户名和邮箱。新账号保持未激活且没有可用密码；邮件激活成功后才加入 `VerifiedUsers`。可在用户列表执行“重新发送账号邀请”，重发后旧链接立即失效。
