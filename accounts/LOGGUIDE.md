# Accounts App — 日志指南

> **文档权重**：70（accounts 日志细节；服从根目录 LOGGUIDE）
> 配套：全项目 LOGGUIDE.md（本地 docs/，git-ignored）

---

## 日志级别快速参考

| Python Logger | Kaomoji | 含义 | 使用场景 |
|---------------|---------|------|---------|
| `logger.info()` | `(✿◕‿◕)` | 一切安好 | 邀请发送/接受、登录成功、密码修改成功 |
| `logger.warning()` | `(ಠ_ಠ)` | 不对劲了 | 登录失败、连续失败、邀请发送失败 |
| `logger.error()` | `(╯°□°）╯︵ ┻━┻` | 出大问题了 | 账户操作异常（极少使用） |

### 日志级别决策树

```mermaid
flowchart TD
    A["发生什么了?"] --> B{"身份认证操作?"}
    B -->|"注册/登录/登出"| C{"操作成功?"}
    C -->|"成功"| D["INFO<br/>(✿◕‿◕)"]
    C -->|"失败"| E{"失败类型?"}
    E -->|"验证失败/密码错误"| F["WARNING<br/>(ಠ_ಠ)"]
    E -->|"连续失败（暴力破解）"| G["WARNING<br/>(ಠ_ಠ) 记录次数"]
    B -->|"密码修改"| H{"修改成功?"}
    H -->|"成功"| D
    H -->|"失败"| F
    B -->|"账户删除/停用"| I["INFO<br/>(✿◕‿◕) 记录 operator"]
```

---

## 职责边界

Accounts app 管理自定义用户模型 (`MyUser`)、邀请制激活、登录、密码修改。本站不开放公共注册。**用户认证操作具有安全敏感性，必须打日志但不得记录密码等敏感信息。**

---

## 日志点清单

### A. 邀请制激活

| 时机 | 级别 | 内容 |
|------|------|------|
| 邀请邮件发送成功 | INFO | user_id（不记邮箱、Token 或 URL） |
| 邀请邮件发送失败 | ERROR | user_id + 异常堆栈，不记邮箱或 Token |
| 邀请接受成功 | INFO | user_id |

```python
logger.info("账号邀请邮件已发送: user_id=%s", user.id)
logger.info("账号邀请已接受: user_id=%s", user.id)
```

> **绝不记录**：邀请 Token、完整邀请 URL、明文密码、密码 hash、邮箱地址、手机号、真实姓名。

### B. 登录

| 时机 | 级别 | 内容 |
|------|------|------|
| 登录成功 | INFO | user_id |
| 登录失败 | WARNING | 用户名（非邮箱），失败原因（密码错误/用户不存在） |
| 连续失败 | WARNING | 用户名，连续失败次数 |
| 达到锁定阈值 | WARNING | 用户名；默认锁定 15 分钟 |

```python
# 登录成功
logger.info(f"User 登录: user_id={user.id}")

# 登录失败
logger.warning(f"User 登录失败: username={username} reason=invalid_password")

# 连续失败
logger.warning("User 登录失败: username=%s reason=invalid_password attempts=%s", username, attempts)

# 已锁定
logger.warning("User 登录锁定: username=%s", username)
```

> 已实现反暴力破解：按“用户名 + 客户端 IP”的 SHA-256 cache key 计数；默认失败 5 次后锁定 15 分钟，成功登录清零。日志不得记录 cache key 或密码。

### C. 登出

| 时机 | 级别 | 内容 |
|------|------|------|
| 登出 | INFO | user_id |

```python
logger.info(f"User 登出: user_id={request.user.id}")
```

### D. 密码修改

| 时机 | 级别 | 内容 |
|------|------|------|
| 密码修改成功 | INFO | user_id |
| 密码修改失败 | WARNING | user_id, 失败原因 |

```python
# 密码修改成功
logger.info(f"User 密码修改: user_id={user.id}")

# 密码修改失败
logger.warning(f"User 密码修改失败: user_id={user.id} reason=old_password_mismatch")
```

> 同样，**绝不记录**新旧密码。

### E. 账户删除/停用

| 时机 | 级别 | 内容 |
|------|------|------|
| 账户停用 | INFO | user_id, operator_id（谁操作的） |
| 账户删除 | INFO | user_id, operator_id |

```python
logger.info(f"User 停用: user_id={target_user.id} operator={request.user.id}")
logger.info(f"User 删除: user_id={target_user.id} operator={request.user.id}")
```

### F. Django Admin 用户操作

Django Admin 中对 `MyUser` 的编辑操作已自动记录 `LogEntry → SecureLogEntry`。不需要在 `admin.py` 中额外加日志。

如需记录非 `LogEntry` 覆盖的操作（如自定义 Admin action），在对应方法中加：

```python
def make_inactive(self, request, queryset):
    for user in queryset:
        logger.info(f"Admin 停用 User: user_id={user.id} operator={request.user.id}")
    queryset.update(is_active=False)
```

---

## 不打日志的位置 (accounts)

| 位置 | 原因 |
|------|------|
| 每次请求的身份验证（`request.user` 获取） | 每个请求都触发，日志洪水 |
| 权限检查 | Django 内部操作，高频 |
| Session 读写 | Redis 操作，无需日志 |

---

## 安全规则（重点）

```
┌─────────────────────────────────────────────────┐
│  ❌ 绝不记录: 密码、密码 hash、邮箱、手机号        │
│  ❌ 绝不记录: Session key、Token、SECRET_KEY      │
│  ✅ 用 user_id 代替用户身份标识                   │
│  ✅ 记录登录失败但仅记录用户名（非邮箱）           │
│  ✅ 连续失败场景记录 attempts 次数                │
└─────────────────────────────────────────────────┘
```

---

## 与其他 App 对比

| App | 复杂度 | 日志量 | 主要日志来源 |
|-----|--------|--------|-------------|
| **accounts** | **低** | **低** | 登录/注册/密码修改 |
| Blogs | 高 | 高 | 文章 CRUD + 修订 + diff |
| comment | 中 | 中 | 评论提交 + 审核 |
| security | 中 | 低 | 审计链验证 |
| boards | 低 | 极低 | seed 命令（一次性） |
| config | 低 | 低 | 侧边栏配置变更 |
| music | 空壳 | 无 | 暂无功能 |
