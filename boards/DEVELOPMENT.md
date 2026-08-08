# Boards 模块 — 开发文档

> **文档权重**：85（boards 当前实现与模块 TODO）
> **模块**: `boards/`  
> **职责**: Board 领域、板块成员关系、角色规则、跨 App Policy，以及板块申请审批
> **依赖**: `Blogs.Category` (ForeignKey)  
> **创建**: 2026-06-22  
> **最后更新**: 2026-08-06 — 文档一致性收尾（最终工作树重跑 47 项回归 + 桌面/移动端视觉验收）

---

## 0. 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-06 | v3.4 | 文档一致性收尾：最终工作树重跑 47 项 Board Index/Policy/文章运行时组合回归 + Django check + Ruff + `git diff --check` 全部通过；桌面 1264 与移动 390 viewport 下三板无横向溢出，DISPATCHES/JOIN/参与 CTA 文本标记在 DOM 中确认；V2GUIDE 清理过时的 K3+后端待接线描述，仅保留 REFUSE 统一接入为剩余收尾 |
| 2026-08-04 | v3.3 | 三个 Index 统一接入公开文章流与后端参与状态；Contributor/Editor/Manager 安全预选 Category 新建文章，Reviewer 跳转 Board-scoped 审核；4 项新文章流测试、47 项组合回归、system check 与 Ruff 完成 |
| 2026-08-04 | v3.2 | 合并 Music/Coding Devenir 前端；补齐 Skate Clip CRUD、Policy 派生的全站/Index 管理入口、板块色主题、统一通知与删除回归修复；相关定向回归与 Django system check 通过 |
| 2026-08-04 | v3.1 | Board Index 闭环第一阶段：Music 排行/封面/外链字段与 Spotify 本地聚合导入；Coding 项目类型、仓库/演示链接与封面；Music/Coding Manager CRUD 后端和 Padif local-only 入口契约。31 项定向测试通过 |
| 2026-08-03 | v3.0 | `membership_admin_linear` M3：新增全局/单成员不可变事件时间线；统一阻止最后 Manager 的停用和降级；增加 mTLS + 证书绑定 privileged Session + 新鲜 TOTP + 精确短语的 super_admin break-glass。56 项定向测试通过，PostgreSQL 行锁用例因本地 SQLite 明确跳过 |
| 2026-08-03 | v2.9 | `membership_admin_linear` M2：新增 `/dashboard/memberships/` 筛选列表及授予、改角色、停用、恢复、Manager 原子交接；写操作要求独立 Permission、privileged Session、原因和一次性目标绑定 TOTP capability；22 项 M2/MFA 定向测试通过 |
| 2026-08-03 | v2.8 | `membership_admin_linear` M1：新增 append-only `BoardMembershipEvent`、Membership `updated_at`、迁移和只读事件 Admin；审批/自助退出接入统一事务内核与 Mongo HMAC 镜像，39 项定向测试通过 |
| 2026-08-03 | v2.7-planning | 修订 `membership_admin_linear`：日常管理改由 Devenir Dashboard + 独立 Permission + TOTP step-up 承载；super_admin 保持只读，仅在 mTLS + 证书绑定 + 密码 + TOTP 全验证后执行 break-glass |
| 2026-08-03 | v2.6-planning（已由 v2.7 替代） | 完成 `membership_admin_linear` 初版 M0：核对 Membership 只读观察、申请审批、自助退出间的生命周期缺口；原拟将写操作置于 super_admin，随后按低频全验证定位改由 Devenir Dashboard 承载 |
| 2026-07-29 | v2.5 | 重新冻结 Board 展示/参与边界：Index 与纯展示 htmx 片段保持公开，Membership 只保护投稿、审核、管理等动作；新增本地 `docs/guides/BOARD_CONTENT_VISIBILITY_GUIDE.md` 作为 K3 前端与后续后端接线契约 |
| 2026-07-29 | v2.4 | BoardAccessRequest 成功后一次性显示 Devenir 中央确认层；提交前强制 accounts purpose 隔离的 10 分钟邮箱验证且成功即消费；新增 `/Blogs/review/` 稿件状态工作区及 Board-scoped 发布文章 QuerySet 筛选 |
| 2026-07-28 | v2.3 | 合并前加固：音乐旧数据双向搬运与往返迁移测试；固定 Board 归属改为 Model 层强制校验；首页过滤无 Index 的 Board；Admin 颜色预览适配 Django 5.2；全项目 215 项测试通过、16 项未来 MFA 契约按设计跳过 |
| 2026-07-27 | v2.1 | Stage 6b：BoardAccessRequest、用户入口、分级审批、事务写入与审计完成；完整测试 179 个 |
| 2026-07-28 | v2.2 | Board Index 后端落地（codex/board-back）：content 模型合并入单一 `models.py`；board 由模型类型固定（auto-default + Admin 隐藏）；`board_index.py` 分派、`BoardIndexView`+`HomieLineView` 路由、Admin 注册完成；board-index 测试 15 项全绿 |
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
├── models.py            # Board / BoardMembership / BoardAccessRequest + Board Index 内容模型（SkateHomie/SkateClip、Music Spotify/Apple、Coding Project/Principle/Experiment）
├── board_index.py       # assemble_context 分派（ASSEMBLERS + 三板 assemble_*）
├── content_forms.py     # Skate/Music/Coding 专属内容表单与周期/链接校验
├── content_views.py     # Manager-scoped 专属内容 CRUD 与 Padif local-only shell
├── admin.py             # BoardAdmin + Membership 只读观察入口 + Board Index 内容模型（superuser）
├── views.py             # boards_context 上下文处理器 + BoardIndexView / HomieLineView
├── access_rules.py      # Board 角色动作矩阵与纯拒绝规则（无 ORM）
├── policies.py          # Post/Comment → Board ORM 解析与统一授权入口
├── tests/
│   ├── test_access_rules.py  # accounts_linear 阶段 1 契约测试
│   ├── test_membership.py    # 阶段 2 ORM 与 Admin 边界测试
│   ├── test_policies.py      # 阶段 3 跨 App Policy 契约测试
│   ├── test_admin_scope.py   # 阶段 4 Dashboard 隔离与阶段 5 action 测试
│   ├── test_stage5_runtime.py # 阶段 5 View/Upload/API/Service 测试
│   ├── test_board_index_models.py  # Board Index 内容模型行为测试
│   ├── test_board_index_views.py   # BoardIndexView / HomieLineView 分派与渲染测试
│   ├── test_board_content_management.py # 内容工作区允许/拒绝与 provider 隔离
│   └── test_spotify_import.py # Spotify 聚合导入与幂等性
├── management/
│   └── commands/
│       ├── seed_boards.py   # 板块种子数据命令
│       ├── import_spotify_export.py # 本地导出 → 年度聚合，不保存原始历史
│       └── seed_permission_test_users.py # 本地角色测试账号
└── DEVELOPMENT.md       # 本文档
```

### 数据流

```
Super Admin (/super_admin/, BoardAdmin)
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
| `updated_at` | DateTimeField | 最近一次状态或角色更新时间；不代替事件历史 |

数据库约束 `unique_board_member` 保证同一用户在同一 Board 只有一条记录。角色调整或停用更新原记录，不堆叠历史角色；后续审批和审计流程引用这条稳定记录。

### BoardMembershipEvent

append-only 关系型事件保存事件类型、来源、角色/active 前后状态、原因、操作者、关联申请，以及 Board/User/actor 的不可丢失快照。Membership、Board 或用户外键删除后可置空，快照仍保留审计语义。模型实例禁止修改和删除，super_admin 仅提供只读观察；状态与事件在同一事务写入，提交后再镜像到 MongoDB HMAC。

### Board Index 内容模型

Board Index 三页（skateboard / music / coding）的内容模型也位于 `boards/models.py`，与 `Board` 同 app。分为三组：

| 组 | 模型 | 所属板块（固定） |
|----|------|------------------|
| Skateboard | `SkateHomie`（成员节点）、`SkateClip`（动作片段） | skateboard |
| Music | `MusicRecordBase`（抽象）+ `SpotifyRecord` / `AppleRecord`（平铺，增加 rank/play_count/minutes/cover/external_url，按 (year, month) 分组） | music |
| Coding | `CodingProject`（GitHub/local_tool/external、仓库/演示链接、封面/精选）、`CodingPrinciple`、`CodingExperiment` | coding |

**关键约束（2026-07-28 用户决策）**：内容模型的 `board` 外键**不由人工选择**，而是由模型类型固定——每个内容模型声明 `BOARD_SLUG` 类属性，`board` 字段的 `default` 通过 `_board_default(slug)` → `_board_for_slug(slug)` 按 slug 自动解析对应 `Board`；`FixedBoardContentModel` 同时在 `clean()` 与 `save()` 层拒绝错误 slug 的 Board，Admin 中 `SuperuserBoardContentAdmin.exclude = ("board",)` 统一隐藏该字段。普通 ORM/脚本写入无法再绕过该归属约束；`bulk_create()` 等绕过 Model `save()` 的批量入口仍不得用于这些内容模型。

- `SkateHomie.memberships` 为 M2M → `BoardMembership`，仅作展示/归属标注，**绝不作为授权依据**（决策 3）。
- `SkateClip.is_public` 过滤在查询层完成（`boards/board_index.py` 的 `assemble_skateboard`），不泄露非公开内容。
- 三组的查询分派由 `boards/board_index.py` 的 `ASSEMBLERS` 表按 `board.slug` 完成，详见 §7 与 `boards/guide/BOARD_INDEX_BACKEND_GUIDE.md`。

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
- 当前禁止新增、修改和删除。Stage 6b 已实现审核入组，普通非 Manager 成员也可自助退出；日常 Manager 处理、无申请直接授予、角色调整、停用和恢复已由独立 Devenir 页面承载。
- 不把模型注册到 `/dashboard/` AdminSite；全站成员查询只通过独立 `/dashboard/memberships/` View，并在查询前复核 dashboard 身份、独立 Permission 与 privileged Session。

M2/M3 已实现受控管理而没有解除 ModelAdmin 只读：日常直接授予、调整角色、停用、恢复和 Manager 原子交接位于 Devenir `/dashboard/memberships/`，要求 active dashboard 身份、独立 Permission、privileged Session 和一次性 TOTP step-up；事件历史位于 `/dashboard/memberships/events/`。所有操作要求原因并写入关系型 `BoardMembershipEvent`，事务提交后再镜像 MongoDB HMAC；默认 add/change/delete 与批量写继续关闭。`/super_admin/` 只增加一个全验证、自定义 URL，用于停用确实没有接替者的最后一名 Manager。PostgreSQL 行锁竞争测试仍需在 PostgreSQL CI/预发布运行。完整状态机与验收标准见 [`accounts/PERMISSIONS_GUIDE.md`](../accounts/PERMISSIONS_GUIDE.md#129-membership_admin_lineardashboard-membership-全生命周期)。

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

Stage 5 已恢复审核/发布/驳回和评论 action，但每个对象都会在事务 Service 或审核 Service 中重新校验 Policy，不再批量直写状态。Stage 6a 已初始化固定全局 Group；Stage 6b 已通过 `/boards/access/`、`BoardAccessRequest` 和审批 Service 自动写入 Membership。Stage 7 已确认全部业务授权不读取遗留 `is_reviewer`，Stage 8 已从 accounts schema 删除该字段；Board 角色只以 Membership + Policy 为事实来源。

当前日常 Membership 写路径已经统一：申请审批、自助退出和 Dashboard 管理都会在同一事务内更新稳定 Membership 并追加 `BoardMembershipEvent`，提交后再 best-effort 镜像 Mongo HMAC。super_admin break-glass 已完成并复用同一状态变更内核；不得直接调用 `BoardMembership.save()` 构造旁路。

Board 独立 Index 的 Music/Coding 前端已由受限 K3 分支完成并合并；路由、QuerySet、Policy 与上下文组装继续由 boards 后端所有。本地 HANDOFF 仅用于临时交接，不进入 Git；长期边界以本节和 V2 指南为准。

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

---

## 7. Board Index 后端（已落地）

> **状态**：已落地（`codex/board-back` 分支）。详细设计文档见 `boards/guide/`（本地非跟踪，git-ignored）。

三个 Board Index 页（Skateboard / Music / Coding）的后端已在 `boards` app 内完整实现：

- **模型**：`boards/models.py` 单文件承载全部内容模型（见 §2 Board Index 内容模型）。
- **分派**：`boards/board_index.py` 的 `ASSEMBLERS`（`{"skateboard": assemble_skateboard, ...}`）+ 三板 `assemble_*` 函数组装上下文；`BOARD_TEMPLATES` 给出每板模板。
- **路由/视图**：`boards/views.py` 的 `BoardIndexView`（`/boards/<slug>/`，按 slug 分派 + 404 未知/下线板块）与 `HomieLineView`（htmx 端点 `/boards/<slug>/homie/<node_index>/`，返回 `_selected_line.html` 片段）。两者属于公开展示面，不要求 BoardMembership；QuerySet 仍必须过滤非公开内容，例如 `SkateClip.is_public=False`。
- **展示/参与边界**：Membership 不控制 Index 的浏览资格，只控制投稿、编辑、审核、评论管理、成员管理和专属内容维护。公开文章入口、参与 CTA、未来受保护动作的 REFUSE 行为及 K3/Codex 边界以本地 `docs/guides/BOARD_CONTENT_VISIBILITY_GUIDE.md` 为准。
- **管理入口**：`SuperuserBoardContentAdmin` 继续为 `/super_admin/` 应急入口；Skate Clip、Music Spotify/Apple 与 Coding Project 已提供 `/boards/manage/...` 业务 CRUD，只接受对应 Board 的 active Manager 或 active superuser，并将 QuerySet 固定到模型所属 Board。主页桌面 mega menu、移动端二级菜单和各 Board Index 的快捷入口均由同一 Policy 派生；隐藏链接不代替服务端鉴权。Dashboard 不注册这些内容模型。
- **迁移**：初始内容模型位于 `0005_board_index_content.py`；Music/Coding 闭环字段位于 `0012_music_and_coding_index_contract.py`。
- **交互**：三类管理页复用 Devenir `manage.css`，以 Board `glitch_color` 作为强调色；成功通知固定显示在导航栏下并自动消失。删除视图显式使用空 `Form`，避免模型表单因无字段 POST 静默失败。
- **测试**：模型、公开 Index、Spotify 导入及专属内容管理均有定向回归；本阶段最后一轮 10 项内容管理测试与 Django system check 通过。

当前公开展示与参与边界见本地、git-ignored 的 `docs/guides/BOARD_CONTENT_VISIBILITY_GUIDE.md`（84）。早期后端详细设计、决策记录与模型背景见本地 `boards/guide/`：

- `BOARD_INDEX_BACKEND_GUIDE.md`（82）：单 app 架构、`Board.slug` 判别、单一 `models.py`、分派视图、路由与 htmx 端点、与 `Board`/`BoardMembership`/Policy 边界、决策记录。
- `SKATEBOARD_BACKEND_GUIDE.md`（80）：`SkateHomie` + `SkateClip`。
- `MUSIC_BACKEND_GUIDE.md`（80）：Spotify / Apple Music 分离模型。
- `CODING_BACKEND_GUIDE.md`（80）：`CodingProject` / `CodingPrinciple` / `CodingExperiment`。

### 7.1 如何继续推进（剩余工作）

后端代码已就绪，前端三页为数据驱动 + mock 降级。当前最大缺口是**没有内容种子数据**（`seed_boards` 只写入 `Board` 行，不写内容模型），因此页面目前只走 mock 分支。建议下一步：

1. **填充内容数据（红色/已解）**：已新增 `boards/management/commands/seed_board_index.py`（Faker 驱动，幂等 + `--reset`），填充三块内容模型；三页已渲染真实数据。
2. **`SkateHomie.avatar` 图片校验与存储策略（黄色）**：本地公开图片约束未定，参考 `docs/guides/BLOG_FOUNDATION_GUIDE.md`（本地）。
3. **`CodingProject.status` / experiment 取值表（黄色）**：状态枚举与展示文案未定。
4. **`SkateHomie.call_sign` 与 `name` 展示区分规则（绿色）**：未定。
5. **Music 排行与月度总结（✅ 第一阶段完成）**：Spotify 年度总量/艺人/歌曲排行和 Apple 月度总量/艺人/歌曲排行已接入 Devenir 页面；封面/外链可手工维护，不复制 Apple 品牌播放器。
6. **mock 降级清理决策（绿色）**：后端已接线，决定是否保留模板 `{% empty %}` mock 分支。

7. **板块申请复用 accounts 短时邮箱验证（✅ 已完成）**：`/accounts/security/email/board-access/` 复用 accounts 通用邮箱挑战；验证码按 purpose + 用户 + Session 隔离，60 秒冷却和每小时发送上限按账号共享，错误次数受限。验证成功签发 10 分钟 Board 专用 Session grant，申请成功立即消费；密码修改 grant/code 不可复用，目标路由由服务端固定，不接收外部 `next`。
8. **Board Index 接入文章入口与文章流（✅ 已闭环）**：三个 Index 统一复用 `Post.publicly_visible_posts()`，每板只展示对应 `Board.category` 最新 5 篇公开已发布文章，不泄露草稿或 staff-only 内容；“查看全部”只在 Category 正常可访问时显示。参与 CTA 由后端根据匿名、可申请、待审核、有效成员和停用状态生成，不在模板推导角色。具备创建能力且 Board 拥有正常、唯一 Category 映射的成员进入带 `?board=<slug>` 的新文章页，服务端再次通过同一 Policy 校验后才预选 Category；Reviewer 进入带 Board 筛选的审核工作区。申请页同样支持安全预选 Board。桌面与移动端自动化视觉检查已完成；REFUSE 模板已存在，后续受保护动作统一接入时不得复制此状态机。
9. **Skateboard Clip 固定展示编排（🟡 部分完成）**：公开 Index 当前由后端生成 `clip_groups`，每 5 条按 2 个 `9:16` + 3 个 `16:9` 展示。两条竖屏共用一个 box，中央信息区宽于两侧媒体，并分为左上/右下两层分别展示两条 Clip 的完整信息；不足 5 条时按现有条数安全降级，移动端转为单列。`/boards/skateboard/clips/` 是按拍摄时间倒序、仅含公开内容的分页浏览入口，不是管理页。后续仍需增加受控方向/比例字段与上传校验，不能永久用展示位置代替媒体元数据。
10. **各 Board 的内容管理工作区（🟡 主体完成）**：Skate Clip、Music Spotify/Apple 与 Coding Project 已有 Devenir 业务 CRUD，服务端仅允许对应 Board Manager/superuser，且 provider 与对象 QuerySet 隔离；可管理入口由 Policy 同步注入全站菜单和 Board Index。Coding Principle/Experiment 与 Board-scoped 文章统一入口仍待实现。Board 创建及前端代码绑定继续为 superuser-only。

板块权限页同时展示当前 active Membership。非 Manager 成员可在复用邮箱短时验证后自助退出；实现只把 `is_active` 设为 False，保留审批记录，并以 Mongo+HMAC 记录退出事件。Manager 退出和存在待审核申请的情况均 fail closed。

Skate Clip 的展示排序属于受保护写操作，只能从 `BoardMembership`/Policy 判定的板块成员工作区进入；公开 Clip List 不展示排序控件，也不能复用为管理入口。
11. **Skate Spot 结构化位置与 PostGIS（🟢 低）**：当前 `SkateClip.spot` 文本足够用于地点展示，不为此新增 MongoDB 业务集合。只有地图视口、附近 Spot、距离排序等需求真实出现后，才评估独立 `SkateSpot`（名称、城市、可空坐标、`exact/approximate/city_only/hidden` 精度与公开状态）并在现有 PostgreSQL 上启用 PostGIS/GeoDjango；精确坐标默认不公开，国内地图供应商坐标不得未经统一转换混存。
12. **Dashboard BoardMembership 全生命周期（🟡 验收，M0–M3 代码完成）**：关系型事件、统一状态 Service、申请/自助/日常 Dashboard、事件时间线与全验证 break-glass 已完成；pending 申请继续 fail closed，不开放物理删除、默认 CRUD 或批量写。剩余工作是在 PostgreSQL CI/预发布执行真实行锁竞争测试，并完成人工 Authenticator + Nginx mTLS 演练。

> 注：`V2GUIDE.md` 分支表当前未列出 `codex/board-back`（仅列 `admin-hardening` 与 `board-index-k3`）。若需把后端分支纳入总览，请确认后由我同步更新 V2GUIDE（权重 100，需你确认）。
