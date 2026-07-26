# PowerAdapterBlogs 日志规范指南

> **文档权重**：75（全项目日志行为的主规范）
> **版本**: 1.1
> **更新**: 2026-06-22
> **受众**: 本项目开发者
> **配套**: 各 app 下的 `APP_LOGGUIDE.md`

---

## 0. 为什么需要这个文档

日志是"事后唯一真相来源"——出了 bug、被攻击、需要公安备案审计，查的都是日志。

好的日志不是"感觉应该加一条"的随机行为，而是对系统关键路径的系统性覆盖。这个文档告诉你：**在什么地方、用什么级别、写什么内容**。

---

## 1. 日志哲学：三个原则

### 原则 1：状态变更必须留痕

任何改变系统状态的操作都要记录。判断标准很简单：

> 如果这条操作删了，你能从日志中还原"谁在什么时候做了什么"吗？

- ✅ 能 → 日志覆盖率合格
- ❌ 不能 → 漏了关键日志点

**具体含义**：
- 数据库写操作（INSERT / UPDATE / DELETE）→ 记录
- 文件系统写操作（上传、生成）→ 记录
- 外部调用（发邮件、调 API）→ 记录
- 只读操作（列表页、详情页 GET）→ 默认不记录

### 原则 2：错误必须有上下文

每条 ERROR 日志必须包含足够信息回答三个问题：

1. **发生了什么** — 错误类型和消息
2. **谁触发的** — user_id / ip / request_path
3. **出问题的是什么数据** — post_id / comment_id / 关键参数

```python
# ❌ 坏日志
logger.error("保存失败")

# ✅ 好日志
logger.error(f"Post 保存失败: post_id={post.id}, user={request.user}, "
             f"slug={post.slug}, error={e}")
```

### 原则 3：敏感信息不得写入日志

以下内容**永远不能**出现在日志中：

- 密码（明文或 hash）
- Token / Session Key
- 用户邮箱（用 user_id 代替）
- HMAC 密钥、SECRET_KEY
- 用户的个人身份信息（身份证号、手机号、真实姓名）

如果必须记录用户身份 → 用 `user.id`（非邮箱、非用户名）。

---

## 2. 日志级别决策树

```
发生了什么事？
│
├── 系统级灾难（数据库挂了 / 磁盘满了 / 密钥丢失）
│   → CRITICAL  立即处理，否则系统无法运行
│
├── 操作失败了（保存失败 / API 调用失败 / 文件上传失败）
│   → ERROR     影响用户，需要排查修复
│
├── 不太对但能继续（缓存未命中 / MongoDB 暂时不可用 / 频率限制命中）
│   → WARNING   需要关注，暂时不影响功能
│
├── 正常的业务操作（文章发布 / 评论审核 / 版本快照 / 管理操作）
│   → INFO      记录"什么事发生了"，用于审计追溯
│
└── 调试信息（变量值 / SQL 查询 / 中间状态）
    → DEBUG     开发排查用，生产环境关闭
```

**本项目 Python 级别映射**：

| Python logger | 语义 | 日志格式 | 本项目用途 |
|---------------|------|----------|-----------|
| `logger.debug()` | 开发调试 | `[time] DEBUG {message}` | 临时排查，提交前删除 |
| `logger.info()` | 业务操作 | `[time] INFO (✿◕‿◕) {message}` | 文章/评论的创建、编辑、删除、审核 |
| `logger.warning()` | 降级/异常 | `[time] WARN (ಠ_ಠ) {message}` | MongoDB 不可用、缓存穿透、频率限制 |
| `logger.error()` | 操作失败 | `[time] ERROR (╯°□°）╯︵ ┻━┻ {message}` | 保存异常、上传失败、外部调用异常 |
| `logger.critical()` | 系统崩溃 | —（fallback 到 ERROR 格式） | 数据库连接丢失、密钥缺失 |

> **Kaomoji 风格说明**：INFO 用花脸 `(✿◕‿◕)` 表示一切安好，WARN 用死鱼眼 `(ಠ_ಠ)` 表示不满，ERROR 用掀桌 `(╯°□°）╯︵ ┻━┻` 表示出事了。这是个人项目的个性风格，不喜欢可以改回纯文本。

---

## 3. 本项目日志基础设施

### 3.1 日志文件

| 文件 | 级别 | 格式 | 内容 | 轮转 |
|------|------|------|------|------|
| `logs/info.log` | INFO+ | `(✿◕‿◕)` 花脸 | 所有正常业务操作 | 5×5MB |
| `logs/warning.log` | WARNING+ | `(ಠ_ಠ)` 死鱼眼 | 需要关注的问题 | 5×5MB |
| `logs/error.log` | ERROR+ | `(╯°□°）╯︵ ┻━┻` 掀桌 | 严重错误 | 5×5MB |
| `console` | DEBUG+ | 复用 INFO 格式 | 开发环境实时输出 | 无 |

### 3.2 如何获取 logger

```python
import logging
logger = logging.getLogger(__name__)
```

用 `__name__` 的好处：日志输出带模块路径（如 `Blogs.views`），一眼知道从哪来的。

### 3.3 当前注册的 logger

```python
# base.py LOGGING 配置
"loggers": {
    "Blogs": {
        "handlers": ["info_file", "warning_file", "error_file"],
        "level": "DEBUG",
        "propagate": False,
    }
}
```

**现状**：只有 `Blogs` 注册了文件 handler。其他 app（comment、security 等）的日志只输出到 console，**不写入文件**。

**建议**：如果需要为其他 app 也输出文件日志，在 `base.py` 中追加 app logger 配置，或统一由 root logger 处理。

### 3.4 自定义日志格式（Kaomoji 风格）

日志格式定义在 `PowerAdapterBlogs/settings/base.py` 中：

```python
info_format = "[{asctime}] INFO (✿◕‿◕) {message}"
warn_format = "[{asctime}] WARN (ಠ_ಠ) {message}"
error_format = "[{asctime}] ERROR (╯°□°）╯︵ ┻━┻ {message}"
```

对应的 formatter：

```python
"formatters": {
    "info":    {"format": info_format,  "style": "{"},
    "warning": {"format": warn_format,  "style": "{"},
    "error":   {"format": error_format, "style": "{"},
},
```

**Kaomoji 含义**：
| 表情 | Unicode | 含义 | 使用场景 |
|------|---------|------|---------|
| `(✿◕‿◕)` | U+273F U+25D5 U+203F U+25D5 | 花朵笑脸，一切顺利 | INFO 日志 |
| `(ಠ_ಠ)` | U+0CA0 U+005F U+0CA0 | 死鱼眼，不满/怀疑 | WARNING 日志 |
| `(╯°□°）╯︵ ┻━┻` | 多字符组合 | 掀桌，愤怒/失控 | ERROR 日志 |

> 这些 kaomoji 只在 `{style: "{"}` 格式下工作。如果改用其他 logger 或 format style，注意编码问题。控制台支持 UTF-8 即可正常显示。

---

## 4. 日志消息格式约定

### 4.1 结构化原则

用 `key=value` 格式让日志可被 grep/awk/jq 解析：

```python
# ✅ 结构化
logger.info(f"Post 发布成功: post_id={post.id} slug={post.slug} "
            f"user={request.user.id} category={post.category_id}")

# ❌ 自然语言（难以 grep）
logger.info(f"用户 {request.user} 成功发布了文章《{post.title}》")
```

### 4.2 操作命名约定

日志消息以 `{资源} {动作}` 开头：

```
Post 创建成功: post_id=...
Post 编辑成功: post_id=... changed_fields=[title,content]
Post 删除: post_id=... slug=...
Comment 提交: comment_id=... post_slug=...
Comment 审核: comment_id=... old_status=... new_status=...
```

### 4.3 exception 日志

记录异常时用 `logger.exception()`（自动附 stack trace）：

```python
try:
    post.save()
except Exception as e:
    logger.exception(f"Post 保存异常: post_id={post.id}")  # 自动附带 traceback
```

---

## 5. Django 各层的日志放置位置

### 5.1 视图层 (views.py)

```
视图入口 (INFO)
↓
业务操作 (INFO/ERROR)
↓
视图出口 (INFO, 可按需省略)
```

```python
class PostCreateView(CreateView):
    def form_valid(self, form):
        response = super().form_valid(form)
        logger.info(f"Post 创建: post_id={self.object.id} slug={self.object.slug} "
                    f"user={self.request.user.id}")
        return response

    def form_invalid(self, form):
        logger.warning(f"Post 创建失败: user={self.request.user.id} "
                       f"errors={form.errors}")
        return super().form_invalid(form)
```

### 5.2 管理层 (admin.py)

Django Admin 操作已有 `LogEntry` + `SecureLogEntry`（SM3-HMAC 签名）。对这两个模型的操作不需要额外日志，它们本身就是审计记录。

如需记录 Admin 层面的业务操作（非 Django 默认 LogEntry 覆盖的），在对应的 `ModelAdmin` 方法中加：

```python
class PostAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        logger.info(f"Admin 编辑 Post: post_id={obj.id} user={request.user.id}")
```

### 5.3 模型层 (models.py)

**`save()` 方法**：记录关键字段变更，特别是会导致副作用的状态变化。

**`delete()` 方法**：始终记录。

**例外**：频率极高的模型（如 `PostVisit`）不要在 `save()` 中打日志，否则日志爆炸。

### 5.4 信号层 (signals.py)

信号天然适合做审计日志（已有 `post_save LogEntry → SecureLogEntry` 链）。其他业务信号如有需要，在信号接收器中加 `INFO` 日志。

### 5.5 管理命令 (management/commands/)

```python
class Command(BaseCommand):
    def handle(self, *args, **options):
        self.stdout.write("任务开始")
        logger.info("generate_posts 开始: count=...")
        try:
            # ... 业务逻辑 ...
            logger.info(f"generate_posts 完成: created={count}")
            self.stdout.write(self.style.SUCCESS(f"成功创建 {count} 篇"))
        except Exception as e:
            logger.exception("generate_posts 异常")
            raise
```

---

## 6. 不该打日志的位置

| 不该打 | 原因 |
|--------|------|
| `PostVisit.save()` | 每次页面访问都触发，日志量爆炸 |
| `UserIdMiddleware` 主流程 | 每个请求都走，日志洪水 |
| 模板标签函数 | 每次渲染都调用 |
| 高频循环体内部 | 性能杀手 |
| `PostDetailView.get_context_data()` | 读操作，无状态变更 |

---

## 7. 日志与审计的区别

在本项目中，有两种"记录"：

| 维度 | 应用日志 (`logger`) | 审计日志 (`SecureLogEntry` / `MongoLogger`) |
|------|---------------------|---------------------------------------------|
| 目的 | 排查问题、监控状态 | 防篡改、公安备案自测 |
| 防篡改 | ❌ 无保护 | ✅ SM3-HMAC 签名 |
| 写到哪里 | 日志文件 (`logs/`) | PostgreSQL (`SecureLogEntry`) / MongoDB |
| 内容粒度 | 技术上下文 + 业务信息 | 操作对象 + 变更快照 |
| 查询方式 | `grep` / `tail` | `audit_log_integrity` / `verify_log()` |
| 典型场景 | "为什么文章保存失败了？" | "谁在什么时候把这篇评论的状态改成了 spam？" |

**规则**：
- 状态变更 → 两条都要：`logger.info()` 记录可读信息 + 审计链自动签名
- 错误排查 → 只用 `logger.error()`，审计链不需要记录错误
- 审计验证 → 只查审计链，应用日志不参与

---

## 8. 给各 App 的指南

每个 app 下都有一份 `LOGGUIDE.md`，列出该 app 的**具体日志点**、**推荐级别**和**示例代码**。

| App | 指南 | 复杂度 |
|-----|------|--------|
| Blogs | [Blogs/LOGGUIDE.md](../../Blogs/LOGGUIDE.md) | 高（核心业务） |
| comment | [comment/LOGGUIDE.md](../../comment/LOGGUIDE.md) | 中 |
| security | [security/LOGGUIDE.md](../../security/LOGGUIDE.md) | 中（审计链路） |
| accounts | [accounts/LOGGUIDE.md](../../accounts/LOGGUIDE.md) | 低 |
| boards | [boards/LOGGUIDE.md](../../boards/LOGGUIDE.md) | 极低（展示型配置） |
| config | [config/LOGGUIDE.md](../../config/LOGGUIDE.md) | 低 |
| music | [music/LOGGUIDE.md](../../music/LOGGUIDE.md) | 空壳 |

---

## 9. 快速参考卡片

```
┌───────────────────────────────────────────────────────────────┐
│  写操作？ → logger.info("资源 动作: key=val...")    (✿◕‿◕)   │
│  失败了？ → logger.exception("上下文")     (╯°□°）╯︵ ┻━┻   │
│  降级了？ → logger.warning("降级描述")              (ಠ_ಠ)    │
│  调试中？ → logger.debug(...) 提交前删                         │
│  数据库挂了？ → logger.critical(...)                           │
│                                                                │
│  永远不要 log：密码、token、邮箱、密钥                           │
│  永远不要 log：高频循环内部                                     │
│  永远记得 log：状态变更、异常、外部调用                          │
│                                                                │
│  日志格式: [{asctime}] LEVEL (kaomoji) {message}              │
└───────────────────────────────────────────────────────────────┘
```
