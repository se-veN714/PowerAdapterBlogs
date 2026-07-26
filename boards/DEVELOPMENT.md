# Boards 模块 — 开发文档

> **文档权重**：85（boards 当前实现与模块 TODO）
> **模块**: `boards/`  
> **职责**: Board 领域、板块成员关系、角色规则、跨 App Policy，以及板块申请审批
> **依赖**: `Blogs.Category` (ForeignKey)  
> **创建**: 2026-06-22  
> **最后更新**: 2026-07-27 — 完成 Stage 6b 权限申请、分级审批与 Membership 自动写入

---

## 0. 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-27 | v2.1 | Stage 6b：BoardAccessRequest、用户入口、分级审批、事务写入与审计完成；完整测试 179 个 |
| 2026-07-19 | v2.0 | 增加仅限 DEBUG 的幂等测试账号命令，覆盖四种 Board 角色和无 Membership 拒绝样本 |
| 2026-07-19 | v1.9 | Stage 5：状态 action、写作 View、上传、修订端点与只读 API 接入 Policy；完整测试 65 个 |
| 2026-07-19 | v1.8 | Stage 4：Board/Post/PostRevision/Comment Admin 接入 Board Policy，新增 8 个运行时隔离测试 |
| 2026-07-19 | v1.7 | 明确 boards 拥有 Membership、Policy 和未来 BoardAccessRequest；accounts 仅提供身份与全局职责 |
| 2026-07-19 | v1.6 | 新增 `policies.py` 跨 App resolver/Policy；Board 新增删除已收紧为 superuser；运行时对象过滤待 Stage 4 |
| 2026-07-19 | v1.5 | 冻结 Board 为 Blogs/comment 跨 App 授权边界；新增/删除 Board 仅限 superuser，当前 Admin 尚待 Stage 4 收紧 |
| 2026-07-13 | v1.4 | 新增 `BoardMembership`、唯一约束、super_admin 只读观察入口及 5 个 ORM/Admin 测试 |
| 2026-07-13 | v1.3 | 新增 `access_rules.py` 纯权限规则与 7 个角色矩阵/拒绝路径测试；尚未接入 ORM 和运行时入口 |
| 2026-07-13 | v1.2 | 权限指南移至 `accounts/PERMISSIONS_GUIDE.md`，Board app 仅保留领域模型与 Policy 实现职责 |
| 2026-07-12 | v1.1 | 新增 `PERMISSIONS_GUIDE.md`：Group + BoardMembership + Policy 三层权限建议（尚未实施） |
| 2026-06-22 | v1.0 | 初始：Board 模型 + 种子数据 + Dashboard 管理 + 上下文处理器 |

---

## 1. 架构概览

### 1.1 App 所有权

boards 是 Board Scope 授权领域的所有者：

- 当前拥有 `Board`、`BoardMembership`、`BoardAccessRequest`、`access_rules.py`、`policies.py` 和审批 `services.py`。
- Stage 4–5 由 boards Policy 被 Blogs/comment 的 Admin、View、API 调用，但 Post 和 Comment 模型仍归各自 App。
- Stage 6b 的 `BoardAccessRequest`、审批服务和 Membership 变更已落在 boards；它们只通过 `settings.AUTH_USER_MODEL` 引用申请人和审批人。
- boards 不处理密码、登录、邮箱验证、MFA 或全局 Group；这些属于 accounts。

```mermaid
flowchart LR
    ACCOUNTS["accounts<br/>提供 MyUser 与全局状态"] --> BOARDS["boards<br/>Membership / Request / Policy"]
    BOARDS --> BLOGS["Blogs 执行文章动作"]
    BOARDS --> COMMENT["comment 执行评论动作"]
    BLOGS --> BOARDS
    COMMENT --> BOARDS
```

图中的双向箭头表示运行时协作，不表示模型所有权互相转移：业务对象仍由 Blogs/comment 保存，最终 Board Scope 判定集中在 boards。

```
boards/
├── __init__.py
├── apps.py              # BoardsConfig
├── models.py            # Board、BoardMembership 模型
├── admin.py             # BoardAdmin + Membership 只读观察入口
├── views.py             # boards_context 上下文处理器
├── access_rules.py      # Board 角色动作矩阵与纯拒绝规则（无 ORM）
├── policies.py          # Post/Comment → Board ORM 解析与统一授权入口
├── tests/
│   ├── test_access_rules.py  # accounts_linear 阶段 1 契约测试
│   ├── test_membership.py    # 阶段 2 ORM 与 Admin 边界测试
│   ├── test_policies.py      # 阶段 3 跨 App Policy 契约测试
│   ├── test_admin_scope.py   # 阶段 4 Dashboard 隔离与阶段 5 action 测试
│   └── test_stage5_runtime.py # 阶段 5 View/Upload/API/Service 测试
├── management/
│   └── commands/
│       ├── seed_boards.py   # 板块种子数据命令
│       └── seed_permission_test_users.py # 本地角色测试账号
└── DEVELOPMENT.md       # 本文档
```

### 数据流

```
Dashboard (BoardAdmin)
    │ POST / PATCH
    ▼
Board 表 (SQLite)
    │ boards_context() 上下文处理器
    ▼
{{ boards }} 模板变量
    │ index.html {% for board in boards %}
    ▼
editorial-section × N (动态渲染)
```

---

## 2. 模型

### Board

| 字段 | 类型 | 说明 |
|------|------|------|
| `slug` | SlugField(64) UNIQUE | 标识符，如 `skateboard` |
| `name` | CharField(64) | 板块名称 |
| `description` | TextField | HTML 描述，渲染到 editorial-body |
| `glitch_color` | CharField(32) | CSS 颜色值，悬停时叠加到 visual |
| `keywords` | CharField(256) | 逗号分隔，竖排展示 |
| `sort_order` | PositiveSmallInteger | 排序（越小越靠前） |
| `category` | FK → Blogs.Category | 关联分类，点击跳转 |
| `is_active` | BooleanField | 启用/禁用 |
| `created_at` / `updated_at` | DateTimeField | 时间戳 |

**属性**：
- `keywords_list` → list（逗号拆分）
- `metadata_words` → list（取前三词，不足时用 name 填充）

### BoardMembership

| 字段 | 类型 | 说明 |
|------|------|------|
| `board` | FK → Board | 权限所属板块；删除 Board 时级联删除 |
| `user` | FK → MyUser | 成员用户；删除用户时级联删除 |
| `role` | CharField(16) | Contributor / Editor / Reviewer / Manager 单一角色 |
| `is_active` | BooleanField | 停用后不授予任何 Board 动作 |
| `created_by` | FK → MyUser, nullable | 人工创建者；删除创建者时保留记录并置空 |
| `created_at` | DateTimeField | 创建时间 |

数据库约束 `unique_board_member` 保证同一用户在同一 Board 只有一条记录。角色调整或停用更新原记录，不堆叠历史角色；后续审批和审计流程引用这条稳定记录。

---

## 3. 种子数据

```bash
# 创建 3 个默认板块
python manage.py seed_boards

# 预览
python manage.py seed_boards --dry-run
```

默认 3 板块：

| slug | name | glitch_color | keywords |
|------|------|-------------|----------|
| skateboard | Skateboard | #4ed7af | Ollie,Grind,Flip |
| music | Music | #b794f4 | Melody,Harmony,Noise |
| coding | Coding | #f6ad55 | Logic,Struct,Create |

### 本地权限手测账号

目标 Board 已启用且绑定 Category 后，可运行：

```bash
python manage.py seed_permission_test_users --board coding
```

命令只允许在 `DEBUG=True` 下运行，并在输出末尾生成一组随机共用密码。也可在纯本地环境用
`--password` 显式指定。命令幂等地创建或重置以下保留账号：

| 账号 | BoardMembership | 用途 |
|------|-----------------|------|
| `perm_contributor` | Contributor | 本人草稿、编辑与提交边界 |
| `perm_editor` | Editor | 板块文章编辑边界 |
| `perm_reviewer` | Reviewer | 审核但不可自审边界 |
| `perm_manager` | Manager | 板块运营管理边界 |
| `perm_no_board` | 无有效 Membership | Dashboard 有入口但对象默认拒绝 |

五个账号都启用 `is_dashboard_user`，但不授予 `is_staff`、`is_superuser`、Group 或直接
`user_permissions`。重复对另一 Board 运行时，命令会停用这些保留账号在旧 Board 的 Membership，
保证每个账号始终是单一角色样本。superuser 双入口测试使用现有管理员账号，不额外生成共享密码管理员。

---

## 4. Dashboard 管理

- URL: `/dashboard/boards/board/`
- 查看/修改权限：仅有效 Manager Membership 可访问对应 Board
- 新增/删除权限：仅激活的 superuser
- Manager 可编辑运营字段与 `sort_order`；`slug`、`category`、`is_active` 只允许 superuser 修改
- 颜色预览：列表显示色块 + 颜色值
- 搜索：name、slug、keywords

> 新增、删除或改变 Board 的 slug/Category/启用状态仍只允许 superuser，因为这些操作可能改变专属模板、SVG、CSS、JavaScript 或授权映射。授权模型与 Django Group 协作方式见 [`accounts/PERMISSIONS_GUIDE.md`](../accounts/PERMISSIONS_GUIDE.md)。

### BoardMembership 观察入口

- URL：`/super_admin/boards/boardmembership/`
- 仅激活的 superuser 可查看。
- 禁止新增、修改和删除；成员写入将在后续审核入组流程中实现。
- 暂不注册到 `/dashboard/`，避免 Board 范围 queryset 尚未接入时泄露跨板块成员关系。

### 跨 App 授权关系

```mermaid
flowchart LR
    MEMBER["BoardMembership"] --> BOARD["boards.Board"]
    POST["Blogs.Post"] --> CATEGORY["Blogs.Category"]
    CATEGORY --> BOARD
    COMMENT["comment.Comment"] --> POST
    MEMBER --> POLICY["boards Policy"]
    BOARD --> POLICY
    POST --> POLICY
    COMMENT --> POLICY
    POLICY --> RESULT["文章 CRUD / 审核 / 评论管理"]
```

Board 是授权边界，不是 Django Group：Group 只承载 `SiteOperators`、`UserManagers` 等全局职责；Contributor / Editor / Reviewer / Manager 的唯一事实来源是 `BoardMembership`。

Stage 6a 已创建 `boards.apply_board_access` 并只授予 `VerifiedUsers`。该 Permission 仅作为申请入口资格，不授予 Board、Post 或 Comment 的任何 CRUD；最终对象授权仍由 Membership + Policy 裁决。

### Stage 4–5 Policy 状态

`policies.py` 已被 Dashboard Admin 的 queryset、对象和关键字段入口调用：

- Post 通过 Category 唯一解析 Board，缺失或歧义映射默认拒绝。
- Comment 通过 Post 继承 Board。
- Policy 检查账号、Board、Membership、角色、作者和自审边界。
- superuser 保留结构和对象应急权限。
- `user_permissions` 和 Group 不会扩大 Board Scope。
- Post Category 表单与 autocomplete 只返回具备创建能力且映射唯一的 Board Category。
- PostRevision 跟随 Post 可见范围；Comment 审核队列仅向本 Board Reviewer/Manager 只读展示。
- 直接输入跨 Board Admin URL 无法读取或修改对象；Manager 编辑他人文章不会改写原作者。

Stage 5 已恢复审核/发布/驳回和评论 action，但每个对象都会在事务 Service 或审核 Service 中重新校验 Policy，不再批量直写状态。Stage 6a 已初始化固定全局 Group；Stage 6b 已通过 `/boards/access/`、`BoardAccessRequest` 和审批 Service 自动写入 Membership。当前完整测试集 179 个全部通过，下一步为 Stage 7 旧字段观察。

Board 独立 Index 视觉在 `codex/board-index-k3` 并行推进，K3 仅修改 Devenir 专用模板/CSS/展示脚本；路由、QuerySet、Policy 与上下文组装仍由 boards 后端所有。本地 HANDOFF 仅用于临时交接，不进入 Git；长期边界以本节和 V2 指南为准。

板块权限申请与审批属于 boards：accounts 只确认用户已登录、激活和完成邮箱验证，boards 负责申请的目标 Board、目标角色、审批人边界、结果及 Membership 更新。

---

## 5. 上下文处理器

```python
# boards/views.py
def boards_context(request):
    """注入活跃板块列表到所有模板"""
    return {'boards': Board.objects.filter(is_active=True)...}
```

已在 `TEMPLATES[0].OPTIONS.context_processors` 注册，无需视图手动添加。

---

## 6. 前端集成

### 模板链

```
index.html
  ├── {% for board in boards %}          ← boards_context 注入
  │   ├── editorial-number              ← forloop.counter (01-99)
  │   ├── editorial-content
  │   │   ├── board.name / description
  │   │   └── board.category (link)
  │   ├── editorial-visual              ← data-glitch-color="{{ board.glitch_color }}"
  │   │   └── _board_visuals.html      ← 按 board.slug 分支渲染 SVG/波形/代码
  │   └── editorial-keywords           ← board.keywords
  └── {% empty %}
      └── _board_fallback.html          ← 静态回退（seed_boards 前）
```

### Glitch 颜色效果

1. `main.js` 在 DOMReady 读取 `data-glitch-color`，写入 CSS 变量 `--glitch-c`
2. CSS `editorial-visual::after` 伪元素使用 `--glitch-c` 作为背景色
3. Hover 触发 `glitch-chromatic` 动画（±3px 水平抖动 + 透明度闪烁）
4. 伪元素 `mix-blend-mode: lighten` 模拟 PS 单通道效果
