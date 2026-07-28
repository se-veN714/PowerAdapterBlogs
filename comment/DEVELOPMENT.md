# Comment 模块 — 开发文档

> **文档权重**：85（comment 当前实现与模块 TODO）
> **模块**: `comment/`  
> **职责**: 博客评论的提交、审核、展示，以及客户端元数据中间件  
> **依赖**: `Blogs.models.Post`, `gmssl.sm3`, `accounts.MyUser`  
> **创建**: 2026-06-22  
> **更新**: 2026-07-29 — 评论表单改为登录账号身份，移除客户端匿名昵称

---

## 0. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v2.6 | 2026-07-29 | 前台仅向登录账号展示评论表单，作者名读取 Profile 公共名称并回退 username；客户端不再提交 nickname，服务端忽略伪造昵称并保留账号归属 |
| v2.5 | 2026-07-19 | Stage 5：Reviewer/Manager 恢复所属 Board 评论 action，逐对象 Policy 校验并保留 MongoDB HMAC 审计 |
| v2.4 | 2026-07-19 | Stage 4：新增 `/dashboard/` Board-scoped 只读评论队列，Reviewer/Manager 仅见所属 Board 评论 |
| v2.3 | 2026-07-19 | 修正 `0003_comment_user` 数据迁移：删除无归属旧评论后增加非空 `user_id`，修复开发库前端查询 500 |
| v1.1 | 2026-07-12 | Comment 强制关联用户；每用户+IP 限流；作者软删除；Admin 审核统一调用 MongoDB HMAC 审计服务；补回归测试 |
| v1.0 | 2026-06-22 | 新建文档，覆盖评论提交、审核、中间件架构 |

---

## 1. 模块架构概览

```mermaid
flowchart TD
    subgraph frontend["前端"]
        USER["用户浏览器"]
    end

    subgraph middleware["中间件"]
        CMM["ClientMetaMiddleware<br/>提取IP/UA/指纹"]
    end

    subgraph views["视图层"]
        CV["CommentView<br/>POST /post/{slug}/comment/"]
        CDV["CommentDeleteView<br/>作者软删除"]
    end

    subgraph models["数据模型"]
        CM["Comment<br/>user/content/status<br/>legacy nickname snapshot"]
    end

    subgraph admin["管理层"]
        CA["CommentAdmin<br/>审核通过/拒绝/标记垃圾"]
    end

    subgraph security["审计链"]
        MOD["moderate_comment()"]
        ML["MongoLogger<br/>SM3-HMAC 审计"]
    end

    USER -->|"每个请求"| CMM
    USER -->|"POST 评论"| CV
    CV -->|"form.save()"| CM
    CA -->|"审核操作"| MOD
    MOD --> ML

    style CMM fill:#e1f5fe,stroke:#0288d1
    style MOD fill:#fff3e0,stroke:#f57c00
    style ML fill:#fff3e0,stroke:#f57c00
```

**设计原则**:
- 评论提交返回 JSON（API 兼容 + HTMX 片段），不跳转页面
- 登录拦截返回 401 JSON 而非 302 重定向
- 客户端指纹使用 SM3 哈希，不存明文 UA/IP 组合
- 评论审核审计由 MongoDB + SM3-HMAC 链独立完成，不依赖应用日志

---

## 2. 文件清单

| 文件 | 类/函数 | 职责 |
|------|---------|------|
| `models.py` | `Comment` | 评论模型（含状态枚举、`get_by_target`） |
| `views.py` | `CommentView` | 评论提交端点（LoginRequired + JSON 响应） |
| `form.py` | `CommentForm` | 表单只接收正文并验证内容≥10字符；作者身份不接受客户端输入 |
| `admin.py` | `CommentAdmin` | Admin 审核操作（approve/reject/mark_spam） |
| `middleware.py` | `ClientMetaMiddleware` | 提取客户端 IP/UA/指纹（每个请求） |
| `middleware.py` | `get_client_ip()` | IP 提取（X-Forwarded-For 反伪造 + 兜底） |
| `apps.py` | `CommentConfig` | App 配置 |

---

## 3. 数据模型

```mermaid
erDiagram
    Comment ||--o{ Comment : "父评论（自引用）"
    Post ||--o{ Comment : "关联文章"
    MyUser ||--o{ Comment : "登录账号归属"

    Comment {
        int id PK
        int post_id FK
        int parent_id FK "nullable"
        string content "max 2000"
        int user_id FK "required"
        string nickname "legacy display snapshot"
        string email "legacy nullable"
        int status "PENDING/PUBLISHED/REJECTED/DELETED"
        datetime created_time
    }
```

`nickname` 与 `email` 暂留为历史兼容列，不再出现在公开评论表单中，也不作为授权或当前显示身份来源。展示名称由 `Comment.author_name` 从关联账号的公开 Profile 名称读取，并回退到 username；服务端会覆盖客户端伪造的同名字段。

### 状态机

```mermaid
stateDiagram-v2
    [*] --> PENDING : 用户提交
    PENDING --> PUBLISHED : 审核通过
    PENDING --> REJECTED : 审核拒绝
    PENDING --> DELETED : 标记垃圾（Admin）/ 用户删除
    PUBLISHED --> DELETED : 用户删除
    REJECTED --> DELETED : 再次标记
    DELETED --> PUBLISHED : 审核恢复（Admin）
```

### 关键方法

| 方法 | 说明 |
|------|------|
| `Comment.get_by_target(post)` | 获取某文章的一级发布评论（不含回复） |
| `CommentForm.clean_content()` | 内容去空白 + 长度≥10 校验 |

---

## 4. 详细工作流

### 4a. 评论提交流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant MW as ClientMetaMiddleware
    participant View as CommentView
    participant Form as CommentForm
    participant DB as PostgreSQL

    User->>MW: POST /post/{slug}/ <br/> (登录账号 + 评论内容)
    MW->>MW: 提取 client_ip/UA/fingerprint
    MW->>View: request 带元数据
    View->>View: 检查登录状态
    alt 未登录
        View-->>User: 401 JSON {"success":false}
    end
    View->>DB: get Post by slug
    View->>Form: CommentForm(request.POST)
    alt 验证失败
        Form-->>View: errors
        View-->>User: 400 JSON + errors
    else 验证通过
        View->>DB: comment.save()
        View-->>User: 200 JSON + HTML片段
    end
```

### 4b. 审核流程

```mermaid
sequenceDiagram
    participant Admin as 管理员
    participant CA as CommentAdmin
    participant Mod as moderate_comment()
    participant Mongo as MongoDB

    Admin->>CA: approve/reject/mark_spam action
    CA->>CA: 更新 comment.status
    CA->>Mod: moderate_comment(comment, new_status)
    Mod->>Mongo: insert_log (SM3-HMAC 审计)
    alt MongoDB 不可用
        Mod-->>CA: WARNING（状态已更新，审计丢失）
    end
    CA-->>Admin: message_user
```

---

## 5. API 端点

| 端点 | 方法 | 格式 | 说明 |
|------|------|------|------|
| `/post/{slug}/` | POST | JSON | 提交评论（仅 `content`，需登录；作者身份由服务端账号确定） |

> 评论列表在文章详情页中通过模板标签 `comment_block` 渲染，无独立 API 端点。

---

## 6. Admin 配置

```python
# /super_admin/：既有批量审核入口
@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['content_short_description', 'post', 'nickname', 'created_time']
    actions = ['approve_comments', 'reject_comments', 'mark_spam']

# /dashboard/：Stage 5 Board-scoped 审核队列
@admin.register(Comment, site=custom_site)
class BoardScopedCommentAdmin(DashboardAdminMixin, admin.ModelAdmin):
    actions = ['approve_comments', 'reject_comments', 'mark_spam']
```

| Action | 目标状态 | 说明 |
|--------|---------|------|
| `approve_comments` | PUBLISHED | 批量通过 |
| `reject_comments` | REJECTED | 批量拒绝 |
| `mark_spam` | DELETED | 批量标记垃圾 |

Dashboard 队列通过 `boards.policies.comments_visible_to_moderator()` 限定 Reviewer/Manager 的有效 Membership Board。每条 action 在写入前再次调用 `can_moderate_comment()`，然后复用 `security.services.moderate_comment()` 写状态和 MongoDB HMAC 审计；即使构造跨 Board queryset 也会跳过非所属评论。

---

## 7. 权限矩阵

```mermaid
flowchart LR
    ANON["匿名用户"] -->|"不可评论<br/>（需登录）"| FORBID["无权限"]
    USER["登录用户"] -->|"提交评论<br/>（status=PENDING）"| CREATE["创建"]
    REVIEWER["Board Reviewer / Manager"] -->|"仅审核所属 Board<br/>逐对象 Policy"| MODERATE["审核 + HMAC 审计"]
    SUPER["超级用户"] -->|"全部权限"| ALL["完全控制"]
```

| 角色 | 提交评论 | 审核评论 | 删除评论 |
|------|---------|---------|---------|
| 匿名 | ✖ | ✖ | ✖ |
| 登录用户 | ✅ (PENDING) | ✖ | ✅ (仅自己的) |
| Board Reviewer / Manager | ✅ | ✅（所属 Board） | ✖ |
| 超级用户 | ✅ | ✅ | ✅ |

---

## 8. 缓存架构

Comment 模块目前无独立缓存。评论列表通过 `comment_block` 模板标签实时查询渲染。

| 缓存层 | 状态 | 说明 |
|--------|------|------|
| 评论列表 | 无缓存 | 每次请求实时查询，量小 |
| IP 解析 | 无缓存 | 每次请求计算，轻量 |

---

## 9. 演进路径

### 当前状态 (v1.0)

- 基础评论提交 + Admin 审核
- 客户端元数据中间件
- 评论数较少，无需复杂架构

### 目标状态 (v2.0)

| 特性 | 当前 | 目标 |
|------|------|------|
| 评论嵌套 | 仅一级回复 | 多级嵌套 + 折叠 |
| 反垃圾 | 无 | 内容过滤 / 频率限制 |
| 通知 | 无 | 被回复者邮件通知 |
| 审核队列 | Admin 手动 | 可配置自动审核策略 |

---

## 10. 文件依赖图

```mermaid
flowchart TD
    models["models.py<br/>Comment"] --> admin["admin.py<br/>CommentAdmin"]
    models --> form["form.py<br/>CommentForm"]
    models --> views["views.py<br/>CommentView"]
    form --> views
    views --> middleware["middleware.py<br/>ClientMetaMiddleware"]

    models --> |"ForeignKey"| BLOG["Blogs.models.Post"]

    style models fill:#e8f5e9,stroke:#388e3c
    style views fill:#e1f5fe,stroke:#0288d1
```

---

## 11. 已知问题 / TODO

| 严重度 | 问题 | 说明 |
|--------|------|------|
| ✅ 已修复 | 评论删除 | Comment 强制关联用户；作者和 superuser 可通过 CSRF 保护的接口软删除 |
| ✅ 已修复 | 开发库缺少 `comment_comment.user_id` | `0003_comment_user` 先清理无法归属的旧评论，再建立非空用户外键；旧数据需重新导入 |
| ✅ 已修复 | 无频率限制 | 按用户 + IP 使用 cache 限制提交频率，默认每分钟 5 条，超限返回 429 |
| ✅ 已修复 | Dashboard 审核 action 缺对象级 Policy | Stage 5 已逐对象调用 Policy，并有跨 Board action + MongoDB 审计回归测试 |
| 🟢 低 | `email` 字段未使用 | Comment 模型有 email 字段但 CommentForm 未包含 |

---

## 12. 附录

### 路由

```
# 评论提交通过文章详情路由处理（POST 到 /post/{slug}/）
# 无独立 URL 配置，CommentView 在 Blogs 的 URL 配置中注册
```

### 中间件配置

```python
# settings/base.py
MIDDLEWARE = [
    ...
    'comment.middleware.ClientMetaMiddleware',  # 放在 AuthenticationMiddleware 之后
    ...
]
```

### 管理命令

| 命令 | 说明 |
|------|------|
| `purge_old_comment_logs` | 清理过期 MongoDB 审核日志 |

### 注意事项

- `redirect_field_name = None` 禁止 Django 302 跳转，确保 API 返回 JSON 而非 HTML
- `ClientMetaMiddleware` 每个请求都触发，正常路径不打日志
- 评论审核审计由 `security` 模块的 `MongoLogger` + SM3-HMAC 链完成，不依赖 `comment` 应用日志
