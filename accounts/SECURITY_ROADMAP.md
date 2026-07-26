# Accounts 安全能力路线图

> **文档权重**：88（v2.5+ 安全规划；状态为规划时不得视为已实现）
> **模块**：`accounts/`、`security/`
> **状态**：H0、H1/Stage 6a–6b 已完成；H2 契约已冻结，下一步从 H2a 绑定与恢复能力开始实现
> **日期**：2026-07-27
> **版本原则**：复杂安全能力默认进入 v2.5+；若前置测试、运维方案和回滚路径提前成熟，可以前移，但不以赶版本为目标。

## 1. 目标与边界

后续安全建设分为三条相互依赖但可独立验收的路线：

1. v2.4：完成 Board Scope 权限颗粒化，为 Manager 身份提供可靠定义。
2. v2.5：为 superuser 建立客户端证书绑定 + TOTP，为 Board Manager 强制启用 TOTP，并以 mTLS 隔离 `/super_admin/`。
3. v2.5+：以密评要求为参照，实践密钥从产生到销毁的全生命周期管理。

这里的“密评实践”是个人项目的合规导向自我验证，不等同于正式商用密码应用安全性评估，也不声称达到某一等级。正式评估还涉及适用范围、合规密码产品、管理制度、运行记录和有资质的评估活动。

## 2. 版本路线

后台加固分支不直接跳到证书和 TOTP。实施顺序为：H0 固定特权入口/拒绝路径测试；H1 完成 Stage 6a/6b 使 Manager 身份稳定；H2 实现 TOTP、恢复码和短时特权 Session；H3 完成独立管理域名的 mTLS Header 契约与应用侧证书绑定；H4 进行恢复、撤销、审计和回滚演练。任何阶段均不得以隐藏 URL 或 `robots.txt` 作为安全边界。

### H0 完成结果（2026-07-27）

- 默认 Django `AdminSite` 已通过 `SuperuserAdminConfig` 替换为 active-superuser-only 的 `SuperuserAdminSite`；`is_staff=True` 不再单独授予 `/super_admin/` 入口。
- `/dashboard/` 继续只接受 active `is_dashboard_user` 或 active superuser；普通账号与 staff-only 账号均被拒绝。
- 自动化测试固定匿名、普通账号、dashboard 用户、staff-only、active superuser 和 inactive superuser 的入口矩阵，并验证 staff-only 凭据无法建立系统后台 Session。
- H0 不实现 TOTP 或 mTLS，也不把 `robots.txt`、URL 隐蔽性视为授权控制。

### H1 / Stage 6a–6b 完成结果（2026-07-27）

- 固定 `VerifiedUsers`、`UserManagers`、`SiteOperators` 三个全局 Group 及其最小 Permission 集。
- UserManagers 与 SiteOperators 的 Permission 已接入 dashboard 外壳及各自 Admin 模块；普通 dashboard 旗标不能越权查看全站审计或账号。
- 迁移不根据旧 `is_reviewer` 推断安全运维身份，避免把 Board 审核职责错误升级为全站审计权限。
- Stage 6b 已通过 `BoardAccessRequest` 审批服务稳定产生 Manager Membership；H2 不再读取旧 `is_reviewer` 推断强制范围。

### H2 分段与实施闸门（2026-07-27 冻结）

H2 必须拆成两个可独立回滚的阶段，禁止在首次引入密钥模型时同时修改登录链路：

| 阶段 | 范围 | 明确不做 | 完成条件 |
|---|---|---|---|
| H2a | TOTP 设备绑定、首次验证码确认、加密 seed、恢复码、撤销/重置审计 | 不拦截登录，不签发 `mfa_verified` Session，不生成仓库内测试 seed | superuser 与 Manager 可在已有登录 Session 中完成绑定和恢复材料验证；失败不会改变现有登录 |
| H2b | 密码后置 TOTP challenge、防重放、限流、短时特权 Session、角色变化失效 | 不加入 mTLS、无密码登录、Microsoft 推送或 Passkey | 仅密码不能进入特权入口；TOTP/恢复码成功、失败、锁定、过期、撤销和回滚均有测试 |

H2a 上线后先保留“可绑定但不强制”的观察窗口。确认至少一个 active superuser 已绑定、恢复码已离线保存且 break-glass 流程经过演练后，才允许开启 H2b。不得把“用户没有设备”自动降级成密码直通，也不得在没有恢复证据时强制唯一管理员启用 MFA。

H2 首期明确强制 active superuser 与任意 active Board Manager。`UserManagers`、`SiteOperators` 同样属于敏感全局职责，是否随 H2b 一并强制是进入 H2b 前的显式决策；旧 `is_dashboard_user` 旗标本身不构成 MFA 身份。推荐最终把两个全局敏感 Group 纳入，但不得在未确认时静默扩大上线范围。

| 版本 | 目标 | 是否修改运行时 | 进入条件 |
|---|---|:---:|---|
| v2.4 | `accounts_linear`：Group + Permission + BoardMembership + Policy | ✅ | 权限矩阵和拒绝路径测试先完成 |
| v2.4.x | 密钥资产清单、用途分类、威胁模型、轮换演练文档 | ❌ 为主 | 不阻塞 Board 权限实施 |
| v2.5 | superuser 证书绑定 + TOTP、Manager 强制 TOTP、`/super_admin/` mTLS | ✅ | Manager 身份稳定；客户端 CA、恢复与回滚方案完成 |
| v2.5+ | 密钥版本、轮换、备份恢复、归档撤销、销毁与审计 | ✅ | 先完成密钥清单和恢复演练设计 |
| v2.6+ 候选 | Passkey、外部 IdP/Entra、硬件或合规密码设备 | ✅，复杂 | 仅在个人站实际需要时评估 |

版本号是实施窗口，不是完成承诺。任何复杂项都可以后移；若依赖和验收条件提前满足，也可以作为较早版本的可选增强。

## 3. TOTP 动态验证码规划

### 3.0 数据模型契约（H2a）

首期单用户只允许一个逻辑设备，避免多设备撤销和恢复语义扩散。建议模型归 `accounts` 所有：

```text
MfaTotpDevice
  user: OneToOne(settings.AUTH_USER_MODEL)
  status: pending | active | revoked
  secret_ciphertext: BinaryField        # 永不保存明文 seed
  secret_nonce: BinaryField             # AES-GCM 唯一 nonce
  key_id: CharField                     # 指向环境中的版本化 KEK
  confirmed_at / revoked_at
  last_accepted_step: BigIntegerField   # 行锁内更新，阻止同一步重放
  auth_version: PositiveIntegerField    # 撤销/重置后使既有特权 Session 失效
  created_at / updated_at

MfaRecoveryCode
  device: ForeignKey(MfaTotpDevice)
  code_hash: CharField                   # 使用 Django password hasher，只展示一次
  used_at: DateTimeField(null=True)
  created_at: DateTimeField
```

约束与密钥边界：

- seed 只在服务内存中产生，写库前使用独立于 Django `SECRET_KEY` 的版本化 KEK 加密；KEK 只来自部署环境/密钥管理设施，不进入数据库、日志、邮件、二维码缓存、仓库或测试快照。
- 每次加密使用独立随机 nonce，并把 `user_id`、设备 ID/临时绑定 ID 与 `key_id` 作为认证上下文；解密失败必须默认拒绝并写不含密文的结果码。
- `pending` 绑定默认 10 分钟过期；首次有效 TOTP 确认后才转为 `active`。中断或过期绑定应删除密文，不能成为可登录设备。
- 首期生成 10 枚高熵恢复码，只保存 password hash；页面只展示一次，单枚成功后立即原子写入 `used_at`。不得提供“重新显示旧恢复码”。
- 撤销或重置递增 `auth_version`、清除可用恢复码并使相关 privileged Session 失效；历史审计只保留 device ID、actor、原因码和时间。

本契约不固定 Python 库。H2a 开工前需要比较维护状态良好的 TOTP 与 AEAD 实现，并固定依赖版本；禁止自行实现 OTP、Base32 或加密算法。

### 3.0.1 登录与 Session 状态机（H2b）

```mermaid
stateDiagram-v2
    [*] --> Anonymous
    Anonymous --> Denied: 密码失败 / 账号停用
    Anonymous --> NormalSession: 密码成功且不要求 MFA
    Anonymous --> PendingMfa: 密码成功且要求 MFA
    PendingMfa --> Denied: challenge 过期 / 次数超限 / 设备不可用
    PendingMfa --> PendingMfa: 错误 TOTP 且未锁定
    PendingMfa --> PrivilegedSession: 新时间步 TOTP 验证成功
    PendingMfa --> RestrictedRecovery: 一次性恢复码成功
    RestrictedRecovery --> PendingMfa: 仅在新设备确认后重新验证
    PrivilegedSession --> StepUpRequired: 15 分钟到期 / auth_version 变化 / 角色变化
    StepUpRequired --> PendingMfa: 重新验证密码或按策略发起 step-up
    PrivilegedSession --> NormalSession: 失去全部特权身份
```

状态机约束：

- 对强制 MFA 的用户，密码通过后不得先调用 Django `login()` 建立完整认证 Session；pending challenge 只保存最小 user ID、签发时间、随机 nonce、目标入口和失败计数，不保存密码、seed 或验证码。
- TOTP 使用 6 位、30 秒周期，首期最多接受当前时间步前后各 1 步；成功时在同一事务内锁定设备并更新 `last_accepted_step`，相同或更旧时间步一律拒绝。
- challenge 默认 5 分钟有效、最多错误 5 次；按账号与客户端地址执行 15 分钟冷却。具体缓存/数据库实现必须保证多进程 Gunicorn 下共享，不能依赖进程内字典。
- 验证成功后才建立/升级 Session，并记录 `mfa_verified_at`、设备 ID 与 `auth_version`。特权有效期首期 15 分钟；到期可保留普通站点 Session，但 `/dashboard/`、`/super_admin/` 及敏感 action 必须重新 step-up。
- 恢复码成功只授予受限的恢复状态，不直接等价于长期特权 Session；用户必须立即重新绑定设备。重置与 break-glass 需要当前密码和更高权限复核，单一 superuser 场景使用预先演练的离线流程，不能降级为仅邮箱重置。
- 所有失败对外使用统一提示，审计内部只记录枚举原因码。任何日志和异常不得包含 seed、`otpauth://` URI、二维码内容、TOTP code 或恢复码。

### 3.0.2 分阶段验收标准

H2a：

- [ ] pending 设备未确认、过期或撤销时不能被当作 active 设备。
- [ ] 数据库、日志、邮件和测试失败输出中均找不到 seed、URI、TOTP code 或恢复码明文。
- [ ] 首次验证码错误不会激活设备；正确验证码只激活一次。
- [ ] 恢复码只展示一次、库中只有 hash、并发消费最多成功一次。
- [ ] 重置需要重新验证当前密码与更高权限边界，并递增 `auth_version`。
- [ ] 未启用 H2b 时，新增模型与绑定页面不改变现有登录成功/失败行为。

H2b：

- [ ] 强制用户仅通过密码后仍未认证，不能访问任何特权页面或 action。
- [ ] challenge 绑定用户、Session 和目标入口；换用户、换 Session、过期或篡改均失败。
- [ ] 当前允许窗口内的新时间步成功，同一步重放及窗口外验证码失败。
- [ ] 第 5 次失败进入共享冷却；更换 Gunicorn worker 或重复请求不能绕过。
- [ ] privileged Session 15 分钟到期，设备撤销、`auth_version` 或特权角色变化后立即失效。
- [ ] 普通非特权用户的登录、Profile 与公开阅读路径不受影响。
- [ ] 功能开关关闭时可回滚到 H2a，但不得删除已加密设备或把密码直通误标为 MFA 成功。

### 3.1 推荐方案

首期使用标准 TOTP：6 位验证码、30 秒周期，通过 `otpauth://` QR Code 绑定。Android Microsoft Authenticator 可按“其他账户”扫描此类二维码；这条路线不依赖 Microsoft Entra，也不提供 Microsoft 推送批准能力。

```mermaid
sequenceDiagram
    actor Admin as superuser / Manager
    participant Login as Django Login
    participant Password as Password Backend
    participant MFA as TOTP Service
    participant App as Microsoft Authenticator
    participant Session as Django Session
    participant Audit as Security Audit

    Admin->>Login: 用户名 + 密码
    Login->>Password: 验证第一因素
    Password-->>Login: 成功
    Login->>Session: 写入 pending_mfa，不授予特权会话
    Login-->>Admin: 展示动态验证码页面
    Admin->>App: 查看当前 6 位验证码
    Admin->>MFA: 提交验证码
    MFA->>MFA: 校验时间窗口、重放与失败次数
    alt 验证成功
        MFA->>Session: 升级为 mfa_verified 会话
        MFA->>Audit: 记录成功事件（不记录 secret/code）
        MFA-->>Admin: 进入 dashboard / super_admin
    else 验证失败
        MFA->>Audit: 记录失败原因码与次数
        MFA-->>Admin: 拒绝或锁定
    end
```

### 3.2 强制范围

- `is_superuser=True`：强制绑定并在特权登录时验证。
- 任意有效 `BoardMembership.role=manager`：强制验证后才能进入 dashboard。
- 普通 Contributor / Editor / Reviewer：首期不强制，后续可配置扩展。
- `SiteOperators`、`UserManagers`：安全上也属于高权限角色，v2.5 实施前应决定是否一并强制；默认建议强制。

### 3.3 必须具备的安全控制

| 严重度 | 控制 | 验收要点 |
|---|---|---|
| 🔴 高 | TOTP secret 加密存储且禁止进入日志 | 数据库泄露时不能直接读取 seed；日志中无 QR URI、secret、验证码 |
| 🔴 高 | 两阶段 Session | 仅密码成功的 `pending_mfa` 会话不能访问任何特权入口 |
| 🔴 高 | 防重放与限流 | 同一时间步验证码不能重复使用；失败计数独立于密码锁定 |
| 🔴 高 | MFA 重置保护 | 重置需重新验证密码并由更高权限复核；全过程写 HMAC 审计 |
| 🟡 中 | 恢复码 | 一次性恢复码仅保存 hash，展示一次，使用后立即作废 |
| 🟡 中 | 时钟与容差 | 服务端时间同步；只接受经过测试的最小时间窗口 |
| 🟡 中 | 角色变化 | 用户获得 Manager 后必须先完成绑定；失去全部特权角色后按策略保留或撤销设备 |
| 🟢 低 | 多设备绑定 | 首期可限制单设备，稳定后再支持多个独立 TOTP device |

### 3.4 明确不在首期实现

- 不接 Microsoft Authenticator 推送通知或号码匹配。
- 不依赖 Microsoft Entra tenant。
- 不以邮件或短信作为同等级 MFA 因素。
- 不在 v2.5 同时引入 Passkey/WebAuthn，避免扩大恢复和兼容性范围。

## 3A. superuser 客户端证书与 `/super_admin/` mTLS

### 3A.1 目标认证链

superuser 访问管理后台时同时经过：

1. Nginx mTLS：验证客户端证书链、有效期和撤销状态，未通过的请求不进入 Django。
2. Django 证书绑定：将 Nginx 传入的 verified 状态、证书序列号 / Subject DN 与 `MyUser.cert_sn`、`cert_subject_dn`、`is_cert_verified` 匹配。
3. TOTP：证书身份通过后再校验动态验证码、重放和失败限流，升级为短时 privileged session。

目标产品形态可以是“证书 + TOTP 登录”，但首轮默认不直接删除密码因素。客户端证书和手机 TOTP 都可能属于 possession factor，尤其二者放在同一设备时并不天然等于两类独立因素；是否无密码化必须经过单独威胁模型与恢复评审。

### 3A.2 Nginx 部署建议

优先建立独立管理域名 / vhost：

```text
public poweradapter.xyz       -> 普通博客，不请求客户端证书
admin.poweradapter.xyz        -> ssl_verify_client on -> 仅代理 /super_admin/
```

Nginx 官方 `ssl_verify_client` 的配置上下文是 `http` / `server`，不是任意 `location`。因此独立 vhost 比在整站 `server` 上设置 `optional` 再按路径判断更清晰，也不会让普通访客遇到客户端证书选择提示。公网站点上的 `/super_admin/` 应拒绝访问或跳转到管理域名，不能保留一个绕过 mTLS 的平行入口。

传递给 Django 的客户端证书信息必须满足：

- 仅在 `$ssl_client_verify = SUCCESS` 时转发；
- Nginx 覆盖或清除外部传入的同名 Header，避免伪造；
- 优先传递序列号、Subject DN、fingerprint 等最小标识，不默认传递完整 PEM；
- Gunicorn 继续只监听 Unix socket / 本机可信链路，不能开放一个绕过 Nginx 的公网端口；
- Nginx 配置更新必须先 `nginx -t`，并保留独立的 break-glass / 回滚操作流程。

### 3A.3 证书生命周期

| 阶段 | 必须定义 | 证据 / 验收 |
|---|---|---|
| 签发 | 独立 Client CA、用途限制、有效期、唯一序列号 | 证书清单不含私钥；错误 CA 被拒绝 |
| 分发 | 私钥生成位置、加密容器、Android/桌面导入步骤 | 私钥不经聊天、邮件或仓库明文传递 |
| 绑定 | serial + Subject DN/fingerprint 与 MyUser 的绑定审批 | 只能绑定 active superuser；重复绑定拒绝 |
| 使用 | mTLS SUCCESS + Django mapping + TOTP | 任意一层失败均不能获得 privileged session |
| 续期 | 新旧证书短暂并行窗口 | 可无停机切换且旧证书按期失效 |
| 吊销 | 丢失、离职、疑似泄露时的 CRL/OCSP 或短证书策略 | 吊销后现有 TLS/特权 Session 均失效 |
| 恢复 | 双人/离线恢复材料或本机紧急流程 | 不降低为仅邮箱重置；全过程审计 |
| 销毁 | 客户端私钥和 CA 旧材料的销毁条件 | 销毁确认与不可再次认证测试 |

### 3A.4 纵深防御与测试

```mermaid
flowchart LR
    TLS["mTLS client certificate"] --> MAP["Django certificate mapping"]
    MAP --> OTP["TOTP + anti-replay"]
    OTP --> SESSION["short privileged session"]
    SESSION --> ADMIN["/super_admin/"]
    TLS --> AUDIT["security audit"]
    MAP --> AUDIT
    OTP --> AUDIT
    SESSION --> AUDIT
```

- [ ] **红色 / 高权重**：无客户端证书、过期证书、错误 CA、已吊销证书均不能到达 `super_admin` 应用页面。
- [ ] **红色 / 高权重**：伪造 `X-SSL-*` / `X-Client-Cert-*` Header 不能绕过 Nginx 或 Django 映射。
- [ ] **红色 / 高权重**：已验证证书不能直接获得权限；必须属于 active superuser 且完成 TOTP。
- [ ] **红色 / 高权重**：证书或 TOTP 撤销后，关联 privileged session 必须失效。
- [ ] **红色 / 高权重**：存在经过演练的 break-glass 与配置回滚；恢复材料不得长期在线明文保存。
- [ ] **黄色 / 中权重**：验证桌面浏览器、Android 证书容器和 Microsoft Authenticator 的实际兼容性。
- [ ] **黄色 / 中权重**：审计日志只记录证书最小标识和结果码，不记录私钥、完整证书、TOTP seed/code。

## 4. 密钥全生命周期规划（v2.5+）

### 4.1 生命周期状态

```mermaid
stateDiagram-v2
    [*] --> Planned: 定义用途/算法/有效期/责任人
    Planned --> Generated: 在受控环境产生
    Generated --> Active: 安全导入或分发后启用
    Active --> Rotating: 到期/策略变更/疑似泄露
    Rotating --> Active: 新版本启用
    Active --> Revoked: 泄露或不再可信
    Active --> Archived: 仅为验证或解密历史数据保留
    Revoked --> Destroyed: 满足保留条件后销毁
    Archived --> Destroyed: 超过归档期限后销毁
    Destroyed --> [*]
```

覆盖环节以“产生、分发、存储、使用、更新、归档、撤销、备份、恢复、销毁”为基线，每个环节都需要责任主体、操作条件、审计证据和失败处置。

### 4.2 第一批资产清单

| 资产 | 用途 | 首要难点 | 初步策略 |
|---|---|---|---|
| `LOG_HMAC_KEY` | MongoDB 审计日志完整性 | 轮换后仍需验证历史日志 | 每条日志记录 `key_id`；旧验证密钥进入只读归档，不立即销毁 |
| Django `SECRET_KEY` | 签名、Session 等框架能力 | 轮换可能使既有签名失效 | 制定 `SECRET_KEY_FALLBACKS` 过渡窗口和会话影响测试 |
| TOTP seed | 特权用户第二因素 | 展示、备份、重置和销毁 | 每设备独立密文；只在绑定时展示；撤销后不可再次验证 |
| TLS 私钥 | HTTPS 服务身份 | 通常由 Web Server/证书工具管理 | 纳入清单但不在 Django 数据库管理 |
| 数据加密密钥（未来） | 敏感字段或备份加密 | 密钥层级与历史数据重加密 | 有真实加密需求后再引入 KEK/DEK，不为演示提前造系统 |

数据库密码、API Token 等应进入“凭据生命周期”清单，但不要与密码学密钥混成同一种资产。

### 4.3 分阶段实施

| 阶段 | 工作 | 可交付证据 |
|---:|---|---|
| K0 | 资产、用途、算法、位置、责任人、有效期清单 | `key_inventory` 文档；不含任何密钥明文 |
| K1 | 定义 Key ID、状态、版本和轮换策略 | 数据字典、状态机、威胁模型 |
| K2 | 先为 `LOG_HMAC_KEY` 增加版本识别和双 key 验证 | 新旧日志均可验证的自动化测试 |
| K3 | 轮换与应急撤销流程 | dry-run、回滚步骤、Mongo HMAC 审计记录 |
| K4 | 加密备份与恢复演练 | 恢复结果、责任人和时间记录；备份不暴露明文 |
| K5 | 归档和不可逆销毁 | 保留条件、销毁确认、销毁后不可恢复测试 |
| K6 | 对照标准形成差距表 | 符合/部分符合/不适用/未验证及证据索引 |

任何实际轮换前必须先证明“能恢复”；不能把生产密钥销毁当作验证销毁流程的第一次演练。

## 5. 风险 / TODO

| 严重度 | 问题 | 处理窗口 |
|---|---|---|
| ✅ | Board Manager 身份稳定性 | Stage 6b 已以 active `BoardMembership.role=manager` 作为 H2 强制范围事实来源 |
| 🔴 高 | `LOG_HMAC_KEY` 若直接轮换会影响历史日志验证 | v2.5+ K2 前禁止无版本轮换 |
| 🔴 高 | TOTP seed 的根加密密钥会引入新的密钥管理问题 | v2.5 设计评审必须说明根密钥来源与恢复方案 |
| 🔴 高 | mTLS 若直接作用于现有整站 vhost，可能干扰普通用户 TLS 握手；若保留公网平行入口又会被绕过 | 优先独立 admin vhost，并对公网 `/super_admin/` 做拒绝测试 |
| 🔴 高 | 客户端 CA 或唯一管理员证书丢失可能把站点管理员永久锁在门外 | 上线前完成离线 CA、break-glass 和回滚演练 |
| 🔴 高 | 仅信任代理 Header 会允许绕过证书验证 | Header 清洗 + Unix socket + Django 二次映射测试 |
| 🟡 中 | MFA 丢失设备后的恢复流程尚未定义 | v2.5 实施前确定恢复码和人工重置边界 |
| 🟡 中 | 个人项目无法凭软件实现本身证明正式密评合规 | 始终标注为自我实践，保留证据但不做合规承诺 |
| 🟢 低 | Passkey 与推送认证体验更好但范围显著扩大 | v2.6+ 按实际需要再评估 |

## 6. 参考依据

- [GB/T 39786-2021《信息安全技术 信息系统密码应用基本要求》](https://std.samr.gov.cn/gb/search/gbDetailed?id=BD89DE8E07393D08E05397BE0A0A4FAD)
- [国家密码管理局：《商用密码应用安全性评估管理办法》](https://www.oscca.gov.cn/sca/xxgk/2023-10/07/content_1061109.shtml)
- [国家密码管理局：《信息系统密码应用测评要求》附录 A——密钥生存周期管理检查要点](https://oscca.gov.cn/sca/xwdt/2020-12/08/1060792/files/d2f1665e78bb4c658ca06bfaaa16eae1.pdf)
- [Microsoft Learn：支持 TOTP 的 Authenticator 应用](https://learn.microsoft.com/azure/active-directory-b2c/multi-factor-authentication)
- [NGINX `ngx_http_ssl_module`：`ssl_client_certificate`、`ssl_verify_client` 与客户端证书变量](https://nginx.org/en/docs/http/ngx_http_ssl_module.html)
