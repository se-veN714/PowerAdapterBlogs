# Accounts 权限颗粒度设计指南（Board Scope）

> **文档权重**：90（当前 Board Scope 权限与 `accounts_linear` 主设计）
> **归档模块**：`accounts/`
> **主要作用域**：`boards.Board`
> **文档职责**：治理整个授权架构；BoardMembership、申请审批与 Policy 的实现归 `boards` App
> **状态**：`accounts_linear` 阶段 0–8 已完成，遗留 `is_reviewer` 字段已删除；`membership_admin_linear` M0–M3 代码已完成，PostgreSQL 真实并发验收尚未执行
> **日期**：2026-08-03（重定 BoardMembership 日常管理与 break-glass 边界）

> **Stage 7 入口收敛（当前规则，优先于下方历史阶段记录）**：`/review/` 是账号、板块权限、稿件、评论审核的统一业务入口；`UserManagers`、`SiteOperators`、Board Reviewer/Manager 均不因 Group 或 Membership 自动获得 `/dashboard/`。`/dashboard/` 只接受 active `is_dashboard_user` 或 active superuser，并在启用强制开关后要求 MFA；其模型注册也受 `DASHBOARD_MODEL_ALLOWLIST` 显式白名单约束，新增 Admin 模型必须经过代码审查。`/super_admin/` 继续作为低频最高权限入口。UserManager 只能在审核中心启停非 staff、非 dashboard、非 superuser 的普通账号，且不能绕过未完成的邮箱邀请；Board Manager 只审批自己板块内可授予的角色。

> **审核中心与投稿边界**：`VerifiedUsers` 和 Contributor 只拥有申请/投稿能力，不得进入 `/review/`；文章审核入口只授予 Board Reviewer/Manager 或 superuser。作者提审与编辑继续在个人主页和文章详情等作者工作面完成。

> **成员退出边界**：已批准的申请记录保持不可变；Contributor、Editor、Reviewer 可在板块权限页通过短时邮箱验证自助停用自己的 `BoardMembership`，不得删除历史。Manager 不能自助退出：存在其他 active Manager 时可由 Dashboard 停用，否则必须原子交接；只有全验证 superuser break-glass 能强制移除最后一名 Manager。存在同板块待审核申请时仍不得退出。

> **Membership 管理边界（M2/M3 已实现）**：日常管理进入 Devenir `/dashboard/memberships/`，要求 active `is_dashboard_user`、独立 Permission、有效 privileged Session 和操作级新鲜 TOTP step-up；`/super_admin/` 保持低频只读观察，仅通过独立的全验证 break-glass URL 停用最后一名 Manager。两者都不开放默认 ModelAdmin CRUD。
> **目标**：以后续功能围绕 Board 展开，在不引入第三方对象权限库的前提下实现最小权限、职责分离和可测试的板块级授权。

## 1. 当前问题

Stage 4 前，`BoardAdmin` 继承 `DashboardAdminMixin`，实际权限只有一个全局开关：

```text
is_dashboard_user=True → 仍可查看、修改所有现有 Board
is_superuser=True      → 可以新增、删除 Board
```

Stage 4 已在 Dashboard Admin 修复这条全量访问路径；当前缺口转移到审核 action、上传、普通 View 和 DRF API。Board 与 Post 仍通过 `Board.category → Post.category` 间接关联，Comment 再通过 Post 继承板块归属，因此所有剩余入口仍必须复用同一跨 App Policy，不能回退到全局旗标。

本项目的 Board 不是可由业务用户动态扩张的论坛分区。每个新 Board 都伴随独立的模板、SVG、CSS 或 JavaScript，因此新增和删除 Board 属于代码结构变更，只允许 superuser；`BoardCreators` 全局 Group 不再进入设计。

## 2. 推荐的三层授权模型

```mermaid
flowchart TD
    USER["MyUser"] --> GROUP["Django Group<br/>仅全站职责"]
    USER --> MEMBERSHIP["BoardMembership<br/>板块角色的唯一事实来源"]
    GROUP --> GLOBAL["全局 Permission<br/>账号管理 / 审计"]
    MEMBERSHIP --> POLICY["Board Policy<br/>跨 App 对象授权"]
    BOARD["boards.Board"] --> POLICY
    POST["Blogs.Post<br/>经 Category 归属 Board"] --> POLICY
    COMMENT["comment.Comment<br/>经 Post 继承 Board"] --> POLICY
    GLOBAL --> ENTRY["全局 Admin / Service"]
    POLICY --> ENTRY2["Board / Post / Comment<br/>View / API / Admin / htmx"]
```

| 层级 | 职责 | 示例 |
|---|---|---|
| Group | 仅承载不带 Board 范围的全站职责 | `SiteOperators`、`UserManagers` |
| Permission | 全局模型或运维动作能力 | `security.run_integrity_audit`、`accounts.manage_user_accounts` |
| BoardMembership | 用户在某个 Board 内是什么角色 | Coding 的 Editor、Music 的 Reviewer |
| Policy | 结合板块角色、对象归属、作者和状态作最终判断 | 只能编辑所属 Board 的文章 |

`is_active`、`is_staff`、`is_superuser` 保留 Django 原生语义；`is_dashboard_user` 只作为 dashboard 入口开关，不代表具体业务权限。旧 `is_reviewer` 已在 Stage 8 删除。

### 2.1 App 职责边界

```mermaid
flowchart LR
    ACCOUNTS["accounts<br/>身份、认证、全局职责"] --> USER["MyUser"]
    ACCOUNTS --> GROUP["Django Group 分配<br/>VerifiedUsers / UserManagers / SiteOperators"]
    USER --> MEMBER["boards.BoardMembership"]
    BOARD["boards.Board"] --> MEMBER
    MEMBER --> POLICY["boards Policy<br/>板块对象授权"]
    BLOGS["Blogs<br/>Post / Category / Revision"] --> POLICY
    COMMENT["comment<br/>Comment / moderation"] --> POLICY
    SECURITY["security<br/>审计能力与日志"] --> GROUP
```

| App | 拥有的业务事实 | 不应承担 |
|---|---|---|
| `accounts` | MyUser、登录/登出、账号启停、邮箱/证书验证、MFA、全局 Group 的编排与用户归组 | Board 角色、板块申请审批、Post/Comment 对象授权 |
| `boards` | Board、BoardMembership、角色矩阵、Policy、BoardAccessRequest 与审批服务 | 密码、登录、MFA、全局 Group 管理 |
| `Blogs` | Post、Category、文章状态机、修订及 Blogs Permission 定义 | 判断用户属于哪个 Board 或复制 Membership 规则 |
| `comment` | Comment、评论状态、提交与审核执行及 comment Permission 定义 | 自行判断 Reviewer 的 Board 范围 |
| `security` | 审计日志、完整性能力及 security Permission 定义 | 分配 Board 角色或维护用户 Group 关系 |

判断口诀：`accounts` 回答 **Who are you globally?**；`boards` 回答 **What can you do here?**。业务 App 拥有自己的模型和动作，在入口处调用 `boards.policies`，不把 Policy 复制回各 App。

`accounts/PERMISSIONS_GUIDE.md` 继续放在 accounts，是因为它治理全局身份、Group 与 Board Scope 的协作边界；这不表示 Board Policy 或 Membership 模型属于 accounts。

## 3. 建议数据模型

```python
class BoardMembership(models.Model):
    class Role(models.TextChoices):
        CONTRIBUTOR = 'contributor', '投稿者'
        EDITOR = 'editor', '编辑者'
        REVIEWER = 'reviewer', '审核者'
        MANAGER = 'manager', '板块管理员'

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='board_memberships')
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name='created_board_memberships')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['board', 'user'], name='unique_board_member'),
        ]
```

第一阶段继续使用 `Board.category` 判断文章所属板块。若未来一个分类可进入多个 Board，或一篇文章可跨板块展示，再增加明确的 `Post.board` 或中间表，不要长期依赖隐式推断。

## 4. 板块内角色建议

| 能力 | 普通用户 | Contributor | Editor | Reviewer | Manager | SiteOperator | superuser |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 查看公开板块/文章 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 在所属板块投稿 | — | ✅ | ✅ | — | ✅ | — | ✅ |
| 编辑自己的草稿 | — | ✅ | ✅ | — | ✅ | — | ✅ |
| 编辑自己已提交/发布的文章 | — | — | ✅，发布内容回退草稿 | — | ✅，发布内容回退草稿 | — | ✅ |
| 编辑他人正文 | — | — | ⚠️ 可选 | — | ✅ | — | ✅ |
| 提交审核 | — | ✅ | ✅ | — | ✅ | — | ✅ |
| 查看所属板块审核队列 | — | — | — | ✅ | ✅ | — | ✅ |
| 通过/驳回他人文章 | — | — | — | ✅ | ✅ | — | ✅ |
| 审核自己的文章 | — | — | — | ❌ | ❌ | — | ✅ |
| 管理评论 | — | — | — | ✅ | ✅ | — | ✅ |
| 修改 Board 运营文案/关键词 | — | — | — | — | ✅ | — | ✅ |
| 修改 Board slug/前端代码绑定 | — | — | — | — | ❌ | — | ✅ |
| 管理板块成员 | — | — | — | — | ✅ | — | ✅ |
| 查看/运行全站审计 | — | — | — | — | — | ✅ | ✅ |
| 创建/删除 Board | — | — | — | — | ❌ | ❌ | ✅ |

“查看公开板块/文章”明确包含 Board Index、Index 的纯展示 htmx 片段、已公开的 Board 专属展示内容和对应 Category 的已发布文章，匿名访问也不要求 Membership。BoardMembership 授予的是参与和治理能力，不是观看资格；不得把 Index 路由本身作为权限申请门槛。

建议默认不允许 Editor 修改他人正文；需要协作编辑时再单独开放，并保留修订记录。Reviewer 只负责审核，不能直接改正文。

## 5. 建议 Permission 划分

Permission 由动作所属的 App 定义；`accounts` 只负责把真正的全局 Permission 编排进 Group，并管理用户的全局 Group 归属。Board 范围动作即使存在 codename，也由 `boards.policies` 结合 Membership 作最终裁决。

### Boards

```text
boards.apply_board_access
boards.view_board_dashboard
boards.change_board_settings
boards.activate_board
boards.manage_board_members
```

Board 的新增和删除不通过 Group 分配：只使用 superuser 边界。上述 Board 内 codename 是 Policy 动作标识，不表示要把 Contributor / Editor / Reviewer / Manager 写入 Django Group。

### Blogs

```text
Blogs.create_board_post
Blogs.change_own_board_post
Blogs.change_any_board_post
Blogs.submit_board_post
Blogs.view_board_review_queue
Blogs.review_board_post
Blogs.publish_board_post
Blogs.unpublish_board_post
Blogs.view_staff_post
```

### Comment / Security

```text
comment.moderate_board_comment
security.view_audit_log
security.run_integrity_audit
```

### Accounts

```text
accounts.manage_user_accounts
```

Django 自带的 `add/change/delete/view` 权限继续保留；自定义权限用于表达业务语义，避免把 `change_post` 同时解释成编辑、审核和发布。

## 6. 统一 Policy 建议

所有 View、API、Admin 和模板调用同一组纯函数，避免重复手写布尔判断：

```python
can_access_dashboard(user)
get_board_role(user, board)
can_create_post(user, board)
can_edit_post(user, post)
can_submit_post(user, post)
can_review_post(user, post)
can_manage_comments(user, board)
can_change_board_settings(user, board)
can_manage_board_members(user, board)
```

关键约束：

```python
def can_review_post(user, post):
    board = board_for_post(post)
    return (
        user.is_superuser
        or (
            get_board_role(user, board) in {'reviewer', 'manager'}
            and post.owner_id != user.id
        )
    )
```

权限失败对外统一返回 403；隐藏内容和 STAFF_ONLY 内容为避免泄露是否存在，继续返回 404。

## 7. Django Group / Permission 如何与 Board 权限协作

Django 原生授权和板块授权解决的是两个不同维度：

| 组件 | 回答的问题 | 是否带 Board 范围 |
|---|---|:---:|
| `Permission` | 系统中是否定义了某个动作 | ❌ |
| `Group.permissions` | 哪类全局角色默认获得哪些动作 | ❌ |
| `user_permissions` | 某个用户的少量例外授权 | ❌ |
| `BoardMembership` | 用户在某个 Board 中担任什么角色 | ✅ |
| Policy | 此用户现在能否对这个对象执行该动作 | ✅，最终裁决 |

Django 的 `user.has_perm()` 默认只判断全局权限。即使 Permission 的名字包含 `board`，它也不会自动理解“只能操作 Coding Board”。因此任何 Board 对象操作都不能只调用 `has_perm()`；必须进入统一 Policy，并同时检查对象所属 Board。

### 7.1 推荐协作规则

1. `Group` 只打包真正跨 Board 的全局职责，不表示任何板块角色，也不为每个 Board 动态创建 Group。
2. `BoardMembership.role` 是板块内角色的唯一事实来源，负责 Contributor / Editor / Reviewer / Manager。
3. Policy 先处理 `is_active` 与 `is_superuser`，再根据动作分别检查全局 Permission 或 BoardMembership。
4. Board 范围内的编辑、审核、成员管理必须命中相应 Membership；拥有同名全局 Permission 也不能绕过范围检查。
5. `user_permissions` 只用于临时或极少量全局例外，不用于代替 Membership。

推荐的全局 Group：

| Group | 用途 |
|---|---|
| `SiteOperators` | 查看并运行审计，不具备文章或成员管理权 |
| `UserManagers` | 在 `/review/accounts/` 启停普通账号；不能分配 Board 角色或操作特权账号 |
| `VerifiedUsers` | 邮箱验证后的基础组，可提交 Board 权限申请；不直接获得任何 Board 操作权 |

Contributor、Editor、Reviewer、Manager 属于板块内角色，应放在 `BoardMembership.role`，否则用户加入 `Editors` Group 后会自动获得所有板块的编辑能力，违反最小权限原则。

> **后台识别提示**：Django 用户编辑页的“组”选择框只显示上述全局 Group，因此不会出现 `Board Manager`。板块角色必须在 `BoardMembership` 或 `/review/boards/` 审批流程中查看；缺少 `Board Manager` Group 是正确状态，不是遗漏迁移。

### 7.2 权限配置的实际交互

```mermaid
flowchart LR
    SU["superuser"] -->|创建并维护| GROUP["Django Group<br/>SiteOperators / UserManagers / VerifiedUsers"]
    SU -->|把 Permission 加入 Group| GPERM["Group.permissions"]
    GROUP --> GPERM
    SU -->|分配全局职责| UGROUP["MyUser.groups"]
    GPERM --> GLOBAL["全局动作资格<br/>user.has_perm()"]
    UGROUP --> GLOBAL

    SU -->|建立或复核| MEMBER["BoardMembership"]
    SU -->|独占新增 / 删除| BOARD["Board<br/>新板块意味着新前端代码"]
    MANAGER["Board Manager"] -->|仅审批自己 Board 的普通角色申请| MEMBER
    MEMBER --> ROLE["板块角色与作用域<br/>board + user + role + is_active"]

    GLOBAL --> POLICY["boards/policies.py"]
    ROLE --> POLICY
    OBJECT["Board / Post / Comment"] -->|解析所属 Board| POLICY
    POLICY --> RESULT{"允许操作?"}
    RESULT -->|是| ALLOW["执行并写审计日志"]
    RESULT -->|否| DENY["403；敏感对象使用 404"]
```

职责边界：

- superuser 维护 Group、Group 中的 Permission，以及用户的全局 Group 归属。
- Manager 只能在自己管理的 Board 中审批 Contributor、Editor、Reviewer 的申请；当前不能直接新建、停用、恢复或删除 Membership，也不能分配 Group、`user_permissions`、`is_staff` 或 `is_superuser`。
- Group 变化只影响全局职责；Membership 变化只影响指定 Board 及其关联的 Post / Comment。
- 两类配置都只提供 Policy 输入，不能绕过 Policy 直接授权对象操作。

### 7.3 一次请求中的实际判定顺序

```mermaid
sequenceDiagram
    actor User as 已登录用户
    participant Entry as Admin / View / API
    participant Auth as Django Auth Backend
    participant Object as Board Object Resolver
    participant Member as BoardMembership
    participant Policy as boards/policies.py
    participant Audit as MongoDB HMAC Audit

    User->>Entry: 请求执行 action(object)
    Entry->>Policy: can_action(user, object)
    Policy->>Policy: 检查 authenticated / is_active
    alt user.is_superuser
        Policy-->>Entry: allow（应急全权路径）
    else 全局动作
        Policy->>Auth: user.has_perm(codename)
        Auth->>Auth: 合并 user_permissions + Group.permissions
        Auth-->>Policy: True / False
        Policy-->>Entry: allow / deny
    else Board 范围动作
        Policy->>Object: board_for_object(object)
        Object-->>Policy: board
        Policy->>Member: 查询 active membership(user, board)
        Member-->>Policy: role / None
        Policy->>Policy: 校验角色、owner、自审限制、对象状态
        Policy-->>Entry: allow / deny
    end
    alt 允许且属于敏感操作
        Entry->>Audit: 记录主体、Board、动作与结果
    else 拒绝
        Entry-->>User: 403；防枚举场景返回 404
    end
```

上述流程中的关键点是：Django Auth Backend 会合并用户直接权限和其所有 Group 的权限，但它不解析 Board；BoardMembership 也不产生 Django 全局 Permission。两者只在 Policy 层汇合。

### 7.4 最终判定方式

```python
def can_review_post(user, post):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True

    membership = get_active_membership(user, board_for_post(post))
    return (
        membership is not None
        and membership.role in {Role.REVIEWER, Role.MANAGER}
        and post.owner_id != user.id
    )
```

全局 Group 动作仍走 Django Permission；Board 新增是本项目的 superuser 专属结构变更：

```python
def can_create_board(user):
    return user.is_active and user.is_superuser
```

这意味着 Group 和 Membership 可以叠加，但不会互相扩大作用域。例如，一个用户可以属于 `SiteOperators` Group，同时只是 Music Board 的 Reviewer：他可以执行全站日志完整性审计，也只能审核 Music Board 中他人提交的文章。Board 的新增和删除仍只属于 superuser。

### 7.5 Admin 中的协作边界

Django Admin 的全局账号和审计模块可以使用 Group Permission 决定菜单和入口是否出现；涉及 Board、Post 或 Comment 时，模块入口、`has_change_permission()`、action、queryset 过滤和保存路径都必须调用 Board Policy。隐藏按钮只是界面层，后端 Policy 才是授权边界。

首期不建议建立 `CodingEditors`、`MusicEditors` 这类组合 Group。Board 增多后会形成“板块数 × 角色数”的 Group 膨胀，也容易发生 Group 与 Membership 状态漂移。

## 8. 已完成的迁移顺序（历史基线）

1. 为 Board、Blogs、comment、security 增加业务 Permission。
2. 新建 `BoardMembership` 和数据迁移。
3. 将现有 `is_dashboard_user=True, is_reviewer=False` 用户迁为默认 Board 的 Editor/Manager，由 superuser 人工复核。
4. 将 `is_reviewer=True` 用户迁为相应 Board 的 Reviewer。
5. 建立 `boards/policies.py`，先让测试使用，再逐步替换 View/API/Admin 判断。
6. dashboard 入口保留 `is_dashboard_user`，模型操作改查 Policy。
7. 权限矩阵测试通过后，停止读取 `is_reviewer`。
8. 最后删除 `is_reviewer` 字段；是否删除 `is_dashboard_user` 另行评估。

不要在同一个迁移中同时创建 Membership、迁数据、删除旧字段，确保每一步可回滚和核验。

## 9. 必测矩阵

- 普通用户不能进入 dashboard，也不能上传正文图片。
- Contributor 只能在所属 Board 投稿和编辑自己的草稿。
- Editor 不能编辑其他 Board 的文章。
- Reviewer 只能看到所属 Board 的审核队列，且不能审核自己的文章。
- Manager 不能查看全站审计，除非同时属于 `SiteOperators`。
- SiteOperator 不能编辑文章、评论或 Board 配置。
- 被停用的 Membership 立即失效。
- superuser 始终可恢复和管理系统。
- View、API 与 Admin 对同一操作给出一致结果。

## 10. 决策建议

| 决策 | 建议 |
|---|---|
| 是否引入 django-guardian | 暂不引入；BoardMembership + Policy 足够，未来对象规则爆炸时再评估 |
| 审核者能否改正文 | 默认不能 |
| 能否审核自己文章 | 禁止，superuser 应急除外 |
| Manager 能否查看审计 | 默认不能，职责与 SiteOperator 分离 |
| 一个用户能否有多个板块角色 | 首期每个 Board 一个互斥角色；不同 Board 可不同。角色变更不表示能力必然累计 |
| Group 是否表示 Editor/Reviewer | 不建议，避免权限扩散到全部 Board |

## 11. 已知风险 / TODO

| 严重度 | 问题 | 建议 |
|---|---|---|
| ✅ | dashboard 用户可修改全部现有 Board | Stage 4 已按 Manager Membership 限定 queryset；slug/category/is_active 只允许 superuser 修改 |
| ✅ | 普通 View/API 与遗留状态动作读取全局旗标 | Stage 5 已改调 Board Policy/Service，并固定跨 Board、staff 旁路与禁止自审测试 |
| 🟡 中 | Board 与 Post 仅通过 Category 间接关联 | 第一阶段封装 `board_for_post()`；未来按产品关系显式建模 |
| ✅ | `/super_admin/` 曾采用 Django 默认 `is_staff` 入口语义 | H0 已替换为 active-superuser-only `SuperuserAdminSite`；staff-only 账号无法建立系统后台 Session |
| ✅ | View/API 权限判断分散 | Admin、普通 View、上传、修订端点和只读 API 均已收敛到 `boards.policies` |
| ✅ | BoardMembership 自动审批 | Stage 6b 已用 BoardAccessRequest/审批 Service 自动创建、变更或恢复 Membership |
| ✅ | 角色矩阵、ORM Policy 与跨入口拒绝路径已有测试 | Stage 4–5 新增 17 个测试；加入手测账号/导航契约后完整测试集 70 个通过 |
| ✅ | Board 权限申请只检查长期 `VerifiedUsers`，未要求本次敏感操作的短时邮箱确认 | 已复用 accounts 通用邮箱挑战：purpose/用户/Session 隔离，10 分钟授权、共享发送限流、失败锁定；成功提交后立即消费 Board grant，改密 grant 不可互用 |
| ✅ 已实现 | BoardMembership 日常全生命周期入口 | Devenir `/dashboard/memberships/` 已提供直接授予、角色变更、停用/恢复、Manager 原子交接和事件时间线；Dashboard 长期 grant 只负责进入，所有写操作仍要求一次性 TOTP step-up；super_admin 仅保留全验证 break-glass |
| 🟡 中 | Board Manager 缺少所属板块文章与专属内容的统一管理入口 | 在业务路由建立 Board-scoped 管理页并复用 Policy；不得为此重新开放 dashboard |

## 12. accounts_linear

以下步骤严格按顺序推进；每一步完成验收后再进入下一步，避免同时修改模型、数据和所有入口。

`accounts_linear` 名称为既有路线标识，继续保留以便 Agent 交接；从阶段 2 开始，BoardMembership、Policy、BoardAccessRequest 和审批服务的代码所有权均属于 `boards`，accounts 只参与用户身份和全局 Group 部分。

| 阶段 | 工作 | 完成条件 |
|---:|---|---|
| 0 ✅ | 固化角色矩阵、Group 名称和 Permission codename | 2026-07-19 修订：移除 BoardCreators，Board 新增/删除仅限 superuser；未改运行时授权入口 |
| 1 ✅ | 先写 Policy 拒绝路径与角色矩阵测试 | `boards/tests/test_access_rules.py` 已覆盖跨 Board、禁止自审、停用成员与角色矩阵 |
| 2 ✅ | 新建 `BoardMembership` 模型、约束和 Admin 只读观察入口 | 2026-07-13 已完成；同一用户在同一 Board 只有一条记录，观察入口仅限 superuser |
| 3 ✅ | 实现 `boards/policies.py` 与跨 App Board resolver | 2026-07-19 已完成；12 个新增 Admin/Policy 测试通过，尚不替换旧入口 |
| 4 ✅ | 接入 Board/Post/PostRevision/Comment 的 queryset、对象与关键字段权限 | 2026-07-19 已完成；跨 Board URL、表单 Category、作者保持与只读审核队列均有测试 |
| 5 ✅ | 接入审核 action、上传接口、普通 View/API | 2026-07-19 已完成；状态 Service 逐对象校验，API 暂定只读并明确拒绝写方法 |
| 6a ✅ | accounts 创建全局 Group 并迁移全局身份 | VerifiedUsers、UserManagers、SiteOperators 已绑定精确 Permission 并接入工作台边界 |
| 6b ✅ | boards 实现 BoardAccessRequest、审批与 Membership 迁移 | Manager/superuser 审批边界生效，用户无需手工勾选权限 |
| 7 ✅ | 停止读取 `is_reviewer`，完成一次等价完整验收 | Admin、初始化和全部授权入口已停止读取；角色流程与自动回归无旧旗标依赖 |
| 8 ✅ | 删除 `is_reviewer`；单独保留 `is_dashboard_user` | `0011_remove_myuser_is_reviewer` 删除 schema 字段，字段缺失契约测试已加入；dashboard 入口旗标不承载业务角色 |

### 12.1 阶段 0 冻结结果

#### 角色语义

| 角色 | 能力定位 | 是否继承前一角色 |
|---|---|:---:|
| Contributor | 投稿、编辑自己的草稿、提交审核 | — |
| Editor | Contributor 能力；可编辑自己的已提交/发布文章，发布内容修改后回退草稿；不能编辑他人正文 | ✅ |
| Reviewer | 查看审核队列、审核/发布他人文章、管理评论；不能编辑正文 | ❌，职责分离 |
| Manager | 投稿、编辑、审核、评论、运营文案和成员管理；不能创建/删除 Board 或修改前端代码绑定 | 组合角色，但仍禁止自审 |

首期 `BoardMembership` 对 `(board, user)` 保持唯一，一次只有一个角色。Editor 切换为 Reviewer 后会失去编辑能力；确实需要同时编辑与审核时，应申请 Manager，而不是给同一 Board 堆叠多个隐式角色。

#### Group 与 Permission 固定名称

| Group | 自动获得的 Permission | 分配者 |
|---|---|---|
| `VerifiedUsers` | `boards.apply_board_access` | 邮箱验证服务自动加入 |
| `SiteOperators` | `security.view_audit_log`、`security.run_integrity_audit` | superuser |
| `UserManagers` | `accounts.manage_user_accounts` | superuser |

Board 内动作的 codename 继续采用第 5 节定义，但不放入全局 Group；Policy 将其作为动作标识，与 Membership role 对照。Django Group 不创建 Contributor/Editor/Reviewer/Manager，也不创建 `CodingEditors` 之类的动态组。

Board 新增和删除由 superuser 独占，不建立 `BoardCreators` Group。原因不是 Django 无法表达 `add_board`，而是本项目新增 Board 等价于引入一组新的前端代码和部署变更，不属于可委派的日常业务操作。

`VerifiedUsers` 由邀请接受服务 `accounts.services.accept_account_invitation()` 自动归组，并已绑定 `boards.apply_board_access`。这只表示用户具备发起申请的资格；Board 权限仍要等 `BoardAccessRequest` 审批通过并写入 Membership 后才产生。

#### 审批边界

- Manager 可审批自己 Board 的 Contributor、Editor、Reviewer 申请及三者之间的角色变更。
- Manager 不得审批自己的申请，不得授予 Manager、全局 Group、`is_staff` 或 `is_superuser`。
- Manager 申请、全局 Group 申请和权限恢复只能由 superuser 审批。
- superuser 保留应急全权，但审批服务仍记录操作者、申请人、Board、原角色、目标角色和结果。

#### 阶段 1 测试边界

阶段 1 只建立不访问数据库的纯规则内核 `boards/access_rules.py`，用于冻结角色矩阵和拒绝条件；它尚未替换任何 View/Admin/API。阶段 2 创建 Membership，阶段 3 再由 `boards/policies.py` 将 ORM 对象适配到这些规则。

### 12.2 阶段 2 实现结果

- `boards.models.BoardMembership` 已实现 Contributor / Editor / Reviewer / Manager 单角色模型。
- 数据库约束 `unique_board_member` 保证同一 `(board, user)` 只有一条记录；角色变化和停用直接更新原记录。
- `created_by` 使用 `SET_NULL`，允许系统初始化或迁移记录没有人工创建者，同时保留成员本身。
- `/super_admin/boards/boardmembership/` 提供完全只读的观察入口，仅激活的 superuser 可见；在 Board 范围 queryset 落地前不注册到 `/dashboard/`。
- ORM、角色枚举对齐、唯一约束和 Admin 拒绝路径已有 5 个测试；完整测试集共 28 个测试通过。
- 本阶段没有改变任何 View、API、BoardAdmin 或 PostAdmin 的运行时授权逻辑。

### 12.3 阶段 3 实现结果

- `boards.policies` 成为 Board、Post、Comment 业务授权的统一 ORM 适配入口。
- `board_for_post()` 通过 Category 解析 Board；未映射或同一 Category 对应多个 Board 时返回 `None`，默认拒绝。
- `board_for_comment()` 通过 Comment → Post → Category → Board 继承相同作用域。
- `get_active_membership()` 同时要求账号、Board 和 Membership 有效。
- Contributor / Editor / Reviewer / Manager 的创建、编辑、提交、审核、发布、评论管理、运营设置和成员管理规则已接入阶段 1 的纯规则内核。
- Contributor 提交文章补充“必须是作者本人”的拒绝条件；Reviewer 与 Manager 继续禁止自审和自发布。
- Django `user_permissions` 即使拥有 `Blogs.change_post` 也不能扩大 Board Scope，已有回归测试固定该边界。
- `can_create_board()`、`can_delete_board()` 和 `can_change_board_structure()` 只允许激活的 superuser。
- `BoardAdmin` 已先行禁止普通 dashboard 用户新增和删除 Board；修改现有 Board 的字段级 Policy 留给阶段 4。
- 完整测试集共 40 个测试通过；本阶段仍未替换任何 Post/Comment View、Admin action 或 API 授权入口。

### 12.4 阶段 4 实现结果

- `BoardAdmin` 只向 Manager 展示其有效 Membership 所属 Board；Manager 可维护运营文案、颜色、关键词和排序，但 `slug`、`category`、`is_active` 以及新增/删除仍为 superuser 边界。
- `PostAdmin` 不再读取全局 `is_reviewer` 决定对象范围：Contributor/Editor 只见自己的所属板块文章，Reviewer/Manager 可见所属板块全部文章；Reviewer 只读，Manager 可编辑。
- Post 新建表单与 Category autocomplete 仅返回用户具有创建能力且 Category→Board 映射唯一的分类；缺失或重复映射继续默认拒绝。
- `PostAdmin` 已移除会在 Manager 编辑他人文章时覆盖 `owner` 的 `BaseOwnerAdmin` 行为，并由测试保证作者保持不变。
- `PostRevisionAdmin` 继承其 Post 的可见范围；dashboard Comment 队列仅对所属 Board 的 Reviewer/Manager 可见，阶段 4 保持只读。
- 非 superuser 的提交、审核、发布、驳回和评论批量审核 action 暂不开放，避免在阶段 5 对状态流转逐项接入 Policy 前形成批量越权入口。
- `boards/tests/test_admin_scope.py` 新增 8 个运行时隔离测试，包括直接访问跨 Board change URL 无法读取或修改对象；完整测试集 56 个全部通过，Django system check 为 0。

### 12.5 阶段 5 实现结果

- 新增 `Blogs/services.py`，提交、通过、驳回、下架均在事务中锁定 Post，并在状态变更前重新调用 Board Policy；Admin action 不再使用批量 `queryset.update()`。
- Dashboard 文章 action 按用户在不同 Board 的 Membership 动态组合；Reviewer/Manager 的评论 action 逐对象调用 `can_moderate_comment()`，继续复用 MongoDB HMAC 审计服务。
- 删除 `DashboardAuthorMixin` 与 `LoggingMixin`，PostCreateView/PostEditView 显式调用 Policy；新建文章强制 DRAFT，编辑已提交或已发布文章自动退回 DRAFT，且保持原作者。
- PostForm、图片上传、STAFF_ONLY 文章、修订正文/diff 与评论提交入口均使用 Board 能力；单独拥有 `is_staff` 不再绕过内部文章范围。
- Devenir 的“新文章/编辑”按钮按 Policy 结果渲染；Category 页面移除未区分用户的片段缓存，避免内部文章 HTML 被共享给匿名用户。
- Post/Category DRF ViewSet 收敛为 Policy-scoped `ReadOnlyModelViewSet`；匿名用户只见公开已发布文章，Board Reviewer/Manager 可见所属 Board 内部文章，所有写方法返回 405。
- Category dashboard 结构管理收紧为 superuser-only；Tag 继续作为全局词汇管理，后续随 Group 初始化复核。
- Stage 5 新增 7 个跨入口测试，Stage 4 增补 2 个 action 测试；完整测试集 65 个全部通过，Ruff 与 Django system check 均通过。

### 12.6 阶段 6a 实现结果

- 模型声明并迁移 `boards.apply_board_access`、`accounts.manage_user_accounts`、`security.view_audit_log` 和 `security.run_integrity_audit`。
- 数据迁移幂等创建 `VerifiedUsers`、`UserManagers`、`SiteOperators`，并使用 `Group.permissions.set()` 固定每组的精确权限集合。
- active 旧账号迁入 `VerifiedUsers`；active 非 superuser staff 收敛到 `UserManagers`；不把遗留 `is_reviewer` 猜测为 `SiteOperators`。
- `UserManagers` 通过 `/review/accounts/` 启停普通账号，但不能进入 `/dashboard/`，不能新增、删除、重发邀请、操作 staff/dashboard/superuser 或修改 Group/Permission。
- `SiteOperators` 通过 `/operations/security/` 查看和运行 HMAC 完整性审计，不进入 `/dashboard/`，也不获得账号、Board 或文章权限。
- Group Permission 只授予对应业务路由能力；任何 Group 都不能授予 `/dashboard/` 外壳或替代 BoardMembership。

### 12.7 阶段 6b 实现结果

- `boards.models.BoardAccessRequest` 保存申请人、Board、目标角色、状态、审核人、审核时原角色、审核说明与时间；数据库条件唯一约束保证同一用户对同一 Board 同时只有一条待审核申请。
- `/boards/access/` 是 `VerifiedUsers` 的服务端表单入口，只展示当前用户自己的申请历史；提交申请本身不会获得任何 Board CRUD。
- `boards.services` 在数据库事务与行锁内处理审批。通过后创建或更新唯一的 `BoardMembership`，驳回不修改 Membership，重复审批被拒绝；事务提交后以 MongoDB HMAC 日志记录操作者、申请人、Board、原角色、目标角色与结果。
- 本 Board Manager 只能审批 Contributor、Editor、Reviewer，不能自审、跨 Board 审批、授予 Manager、恢复停用 Membership 或变更已有 Manager；后两类操作与 Manager 申请只允许 superuser。
- Manager Membership 只获得所属 Board 的 Policy 权限与审核中心相应入口，不获得 `/dashboard/` 外壳，也不会因此获得账号管理、安全审计或全局 Group 管理权限。
- Board 权限申请统一在 `/review/boards/` 调用同一审批 Service；`/super_admin/` 只保留最高权限观察和应急能力，`/dashboard/` 不再承载申请审批。
- Stage 6b 新增 16 个申请、越权、幂等、回滚和 queryset 隔离测试；完整测试集 179 项通过，Django system check 为 0。

```mermaid
sequenceDiagram
    actor User as VerifiedUser
    participant View as /boards/access/
    participant Request as BoardAccessRequest
    participant Review as Manager / superuser
    participant Service as boards.services
    participant Member as BoardMembership
    participant Audit as MongoDB HMAC Audit

    User->>View: 选择 Board、角色并提交
    View->>Request: 创建唯一 pending 申请
    Review->>Service: 批准或驳回
    Service->>Service: 校验同板块、禁止自审与角色边界
    alt 批准且校验通过
        Service->>Member: 原子创建或更新唯一 Membership
        Service->>Request: 标记 approved 并记录审核快照
    else 驳回
        Service->>Request: 标记 rejected，不改 Membership
    end
    Service-->>Audit: 事务提交后记录审核结果
```

`accounts_linear` 已完成 **阶段 8**：`is_reviewer` 不再存在于当前模型或数据库 schema。历史迁移 `0002_add_is_reviewer` 必须保留，以支持旧数据库沿迁移图升级；新迁移 `0011_remove_myuser_is_reviewer` 承担最终删除。

### 12.8 Stage 7–8 完成记录

Stage 7 的等价流程与代码审计已经完成，Stage 8 删除迁移已建立。后续验收继续覆盖账号创建、Board 申请/审批、投稿、审核、评论管理和双后台登录，但不再保留旧字段作为回退授权源。

- `/super_admin/`、初始化命令和测试账号均不再展示、分配或写入 `is_reviewer`。
- 当前 `MyUser` 模型字段集合明确不包含 `is_reviewer`。
- 所有 Board 操作继续由 `BoardMembership`、Policy 和 Service 决策；代码审计中不存在旧旗标授权读取。
- `is_dashboard_user` 继续只控制 Dashboard 外壳入口，并与 Board 角色分开评估。

### 12.9 membership_admin_linear：Dashboard Membership 全生命周期

#### 12.9.1 当前事实与缺口

截至 2026-08-03，`BoardMembership` 已注册到 `/super_admin/`，但 `BoardMembershipObservationAdmin` 的新增、修改和删除权限均返回 False，所有字段也只读。这不是迁移或注册遗漏，而是 Stage 2 为防止 Admin 绕过 Policy/Service 而保留的观察模式。

Stage 6b 的申请审批可以创建、变更或恢复 Membership，普通非 Manager 成员也可在短时邮箱验证后自助停用自己。M1/M2 已补齐下列日常站务入口，并继续禁止通用 ModelAdmin CRUD：

- 首位 Manager 或应急成员的直接授予；
- Manager 的停用、降级与交接；
- Dashboard 授权管理者主动调整现有角色、停用成员或恢复停用成员；
- 无用户申请时的紧急纠错；
- 将上述动作作为结构化、可查询且不会因 Mongo 暂时不可用而丢失的领域历史。

#### 12.9.2 目标状态机

```mermaid
stateDiagram-v2
    [*] --> Absent: 尚无 Membership
    Absent --> Active: 申请批准 / Dashboard 直接授予
    Active --> Active: 申请批准变更 / Dashboard 调整角色
    Active --> Inactive: 成员自助退出 / Dashboard 停用
    Inactive --> Active: 申请批准恢复 / Dashboard 恢复
    Active --> Active: Dashboard 原子完成 Manager 交接
    Inactive --> [*]: 仅随 Board/User 删除级联，不提供人工删除
```

已批准或已驳回的 `BoardAccessRequest` 永不改写为“撤回”；退出和管理员撤销都只改变稳定 Membership 的 active 状态，并新增事件。停用时保留原角色，恢复时必须显式确认恢复后的角色。

#### 12.9.3 Dashboard 日常操作矩阵

| 操作 | 入口 | 关键约束 | 结果 |
|---|---|---|---|
| 直接授予 | Devenir `/dashboard/memberships/grant/` | active Board、active 非 superuser 用户；无同 Board pending 申请；原因必填 | 新建 active Membership + `granted` 事件 |
| 调整角色 | Membership 对象页 | active Membership；新旧角色不同；无 pending 申请；原因必填 | 原记录更新 + `role_changed` 事件 |
| 停用 | Membership 对象页 | active Membership；无 pending 申请；原因必填 | `is_active=False` + `deactivated` 事件 |
| 恢复 | Membership 对象页 | inactive Membership；active Board/用户；无 pending 申请；明确目标角色与原因 | `is_active=True` + `reactivated` 事件 |
| Manager 交接 | 专用确认页 | 新旧成员、同一 Board、目标用户有效、无相关 pending；原因必填 | 单事务内先授予/晋升新 Manager，再降级或停用旧 Manager |
| 查看历史 | `/dashboard/memberships/events/` 或单 Membership 历史 | 具备日常管理资格与 privileged Session | 按时间、类型、来源、Board 和快照文本筛选关系型事件 |

不提供通用批量写操作，也不开放 Django 默认 `add/change/delete` 表单。Membership 管理使用第一方 Django View + Template + htmx 的 Devenir 页面，每个按钮提交到命名明确的业务 URL，再由 `boards.services` 执行。`/review/`、`UserManagers`、`SiteOperators` 和普通 Board Manager 均不能调用全站 Membership 管理 Service。

日常写操作的服务端资格必须同时满足：active `is_dashboard_user`、独立 `boards.manage_all_board_memberships` Permission、有效 privileged Session，以及为本次操作签发的新鲜 TOTP step-up grant。grant 绑定用户、Session、purpose 和目标操作，最长 5 分钟且成功后立即消费；仅隐藏按钮、邮箱验证码或仍然有效的普通登录 Session 都不能代替它。superuser 即使能进入 Dashboard，也必须遵守同一日常写操作验证，不因 `is_superuser` 自动跳过 step-up。

`/super_admin/` 不承载日常 Membership CRUD。它只保留只读观察，以及“无接替者时强制停用最后一名 Manager”“修复不可能由正常状态机产生的数据异常”等 break-glass 动作；执行前必须已经完成 TLS 1.3 mTLS、Django `ClientCertificateBinding`、账号密码和 TOTP 全验证，并继续要求高风险二次确认与原因。

#### 12.9.4 一致性与冲突规则

1. 所有日常写操作验证 actor 的 dashboard 身份、独立 Permission、privileged Session 和一次性 TOTP step-up；break-glass 另验证 active superuser 与完整证书链。在 `transaction.atomic()` 内对 Membership、相关 pending 申请和交接双方记录使用行锁，不能只依赖按钮是否可见。
2. 同一用户与 Board 存在 pending `BoardAccessRequest` 时 fail closed，先批准或驳回该申请；不得让后台修改与旧申请竞态并在之后意外覆盖新状态。
3. 申请批准、成员自助退出、Dashboard 日常操作和 super_admin break-glass 最终复用同一 Membership 状态变更内核，避免多套更新规则漂移。
4. superuser 本身通过 Policy 的应急路径访问全部 Board，不为其创建误导性的 Membership；staff、dashboard 身份与 Board 角色仍可正交叠加。
5. 不允许相同角色/状态的空操作；不允许向 inactive Board 或 inactive 用户授予/恢复，但允许通过 Dashboard 或 break-glass 停用其现有 Membership。
6. Membership 不提供人工物理删除。Board/User 的既有级联删除行为暂不改变，但事件必须保留 Board、用户、角色和操作者快照，避免外键删除后审计语义丢失。
7. Dashboard 日常停用不得制造零 Manager 状态，必须使用原子 Manager 交接；只有完成全验证的 superuser break-glass 才能在明确确认后强制停用最后一名 Manager。
8. Membership 管理不复用 Board 申请的邮箱 grant。Dashboard 写操作使用新鲜 TOTP step-up；super_admin break-glass 使用 mTLS + Django 证书绑定 + 密码 + TOTP 全验证，两条 grant/purpose 不得互用。

#### 12.9.5 关系型事件与 Mongo HMAC 镜像

已新增并迁移 append-only `BoardMembershipEvent`，保存 event type、Membership 可空引用、Board/User/角色/active 状态前后快照、actor 可空引用、来源（申请审批、自助退出、dashboard、super_admin break-glass、系统迁移）、原因、关联 `BoardAccessRequest` 和创建时间。

事件必须与 Membership 变更在同一关系型事务中写入；任何一方失败都整体回滚。事务提交后再以 `transaction.on_commit()` 镜像到 MongoDB HMAC 日志。Mongo 写入仍是 best effort，但关系型事件是业务历史的可靠基线；Mongo 负责防篡改自我实践和跨日志完整性核验，不再是直接管理动作的唯一记录。

`BoardMembershipEvent` 的 Django Admin 观察入口只允许 superuser 查看，禁止新增、修改和删除；`BoardMembership.updated_at` 已落地，供观察最近变更时间，历史角色不能从该字段推导，必须读取事件。具备全站 Membership 管理资格的 dashboard 用户可在 Devenir 事件时间线查看全局或单 Membership 历史；页面读取快照，因此关联对象删除后事件语义仍可显示。

#### 12.9.6 分阶段实现与验收

| 阶段 | 状态 | 工作 | 验收标准 |
|---:|---|---|---|
| M0 | ✅ 历史设计基线 | 冻结状态机、Dashboard 日常操作、TOTP step-up、super_admin 全验证与审计边界 | 后续 M1–M3 已实现；本行只保留设计追溯，不代表当前功能仍处于规划 |
| M1 | ✅ 代码完成 | 新增 `BoardMembershipEvent`、`updated_at`、统一状态变更 Service 与迁移 | 关系型事件与状态同事务；行锁、回滚、pending 冲突、无操作拒绝、快照保留和事件不可变测试通过 |
| M2 | ✅ 代码完成 | Devenir Dashboard Membership 列表与五类写操作、独立 Permission、privileged Session 复核及一次性 TOTP step-up | 默认 CRUD 仍关闭；目标/动作/用户/Session 绑定和单次消费测试通过；最后一名 Manager、pending 竞态与非法状态 fail closed |
| M3 | ✅ 代码 / 🟡 PostgreSQL 待验 | 事件时间线、统一 Manager 连续性约束及全验证 super_admin break-glass 已实现；PostgreSQL 双请求竞争测试已提供 | 56 项 M3 定向回归通过；SQLite 明确跳过行锁用例，需在 PostgreSQL CI/预发布运行后关闭并发验收 |

`/super_admin/boards/boardmembership/` 必须永久保持默认 CRUD 只读；不得解除 `readonly_fields`、把 `has_change_permission()` 改为 True，或让 dashboard 复用 ModelAdmin 表单。break-glass 只能是命名明确、全验证、单对象且追加事件的例外 URL。

## 13. 参考依据

- [Django 5.2：用户、Group 与 Permission](https://docs.djangoproject.com/en/5.2/topics/auth/default/#groups)
- [Django 5.2：自定义授权后端](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/#handling-authorization-in-custom-backends)
