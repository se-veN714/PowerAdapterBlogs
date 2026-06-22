# PowerAdapterBlogs V2 — 开发指南

> **版本**: v2.3-prerelease  
> **更新**: 2026-06-22  
> **状态**: P0/P1/P2 已完成，v2.2 diff 优化完成，下一项 v2.1 演进  
> **继承**: V1 所有基础设施（Bulma 主题、Redis 缓存、Waitress/Nginx 部署）

---

## 0. V2 需求总览与优先级

| 优先级 | 需求 | 类型 | 预计工时 |
|--------|------|------|---------|
| **P0** | MongoDB 日志完整性修复 | 🐛 Bugfix | 3-4h |
| **P1** | 文章修订追踪 · Phase 1（后端） | ✨ Feature | 6-8h |
| **P2** | 文章修订追踪 · Phase 2（前端） | ✨ Feature | WebStorm 完成 |
| **P3** | Boards 首页板块管理 + Glitch 颜色效果 | ✨ Feature | 2-3h |
| **P4** | Dashboard 批量分行 Action + rewrap_posts 命令 | ✨ Feature | 1-2h |

> **前端说明**：前端（devenir 主题、timeline CSS/JS）在 WebStorm 中独立完成，不在本指南后端范围内。

---

## 1. P0 Bugfix：MongoDB 日志完整性修复 ✅ 已完成

> **完成日期**: 2026-06-22 · 4 个问题全部修复

### 1.1 问题诊断

审查 `security/` 模块后，发现以下 4 个问题：

#### 问题 A：MongoDB 集合命名错误 🔴

`security/mongo_client.py:55`
```python
self.collection = self.db[conf["DB_NAME"]]  # ❌ 集合名 = 数据库名
```
应该用：
```python
self.collection = self.db[conf.get("COLLECTION", "audit_logs")]  # ✅
```

**影响**：所有通过 `MongoLogger` 写入的日志进入名为 `poweradapter_mongo` 的集合，而不是预期的 `audit_logs` 集合。

#### 问题 B：MongoDB 日志无验证能力 🔴

`SecureLogEntry`（PostgreSQL 端）有完整的 `audit()` / `audit_all()` 验证流程，但 `MongoLogger` 只写入了 HMAC，没有任何 `verify_log()` / `audit_logs()` 方法。写了签名但从不校验，形同虚设。

#### 问题 C：LOG_HMAC_KEY 硬编码 🟡

`develop.py:37` 硬编码了 32 字节 key，但 `product.py` 中没有对应的环境变量注入。生产环境部署时这个 key 要么为空导致 crash，要么用开发 key（不安全）。

#### 问题 D：SecureLogEntry compose_message 鲁棒性不足 🟢

`security/models.py` 用 `|` 分隔字段拼接消息。`change_message` 是 Django Admin 的 JSON 字符串，理论上可以包含 `|`，导致 HMAC 校验时消息不一致。

### 1.2 修复方案

#### 修复 A & B：重写 MongoLogger

```python
class MongoLogger:
    def __init__(self):
        conf = settings.MONGO
        # ... 连接代码不变 ...
        self.collection = self.db[conf.get("COLLECTION", "audit_logs")]  # 修复A
        self.hmac_key = settings.LOG_HMAC_KEY

    def insert_log(self, action: str, data: dict):
        now = datetime.utcnow()
        data_bytes = dict_to_bytes(data)
        hmac_val = sm3_hmac(self.hmac_key, data_bytes)
        doc = {
            "action": action,
            "data": data,
            "hmac": hmac_val,
            "created_at": now,          # 新增时间戳
            "verified": False,           # 新增验证标记
        }
        return self.collection.insert_one(doc)

    def verify_log(self, doc_id) -> bool:
        """验证单条日志 HMAC（修复B）"""
        doc = self.collection.find_one({"_id": doc_id})
        if not doc:
            return False
        expected = sm3_hmac(self.hmac_key, dict_to_bytes(doc["data"]))
        is_valid = (doc["hmac"] == expected)
        self.collection.update_one(
            {"_id": doc_id},
            {"$set": {"verified": is_valid, "verified_at": datetime.utcnow()}}
        )
        return is_valid

    def audit_all(self) -> dict:
        """全量审计，返回统计（修复B）"""
        total = tampered = verified = 0
        for doc in self.collection.find({"verified": False}):
            total += 1
            if self.verify_log(doc["_id"]):
                verified += 1
            else:
                tampered += 1
        return {"total": total, "verified": verified, "tampered": tampered}
```

#### 修复 C：KEY 环境变量化

```python
# base.py
LOG_HMAC_KEY = os.getenv("LOG_HMAC_KEY", "").encode()
if not LOG_HMAC_KEY:
    import warnings
    warnings.warn("LOG_HMAC_KEY not set! Log integrity is disabled.", RuntimeWarning)
```

生产 `.env` 中：
```
LOG_HMAC_KEY=<32字节 base64 或 hex>
```

#### 修复 D：消息组合改用 JSON

```python
# models.py SecureLogEntry
@staticmethod
def compose_message(entry: LogEntry) -> bytes:
    """改用 JSON 序列化，避免分隔符冲突"""
    return json.dumps({
        "id": entry.id,
        "action_time": entry.action_time.isoformat(),
        "user_id": entry.user_id,
        "content_type_id": entry.content_type_id,
        "object_id": entry.object_id,
        "object_repr": entry.object_repr,
        "action_flag": entry.action_flag,
        "change_message": entry.change_message,
    }, sort_keys=True, ensure_ascii=False).encode("utf-8")
```

### 1.3 实施步骤

1. 修复 `mongo_client.py` 集合命名（修复 A）
2. 在 `MongoLogger` 中添加 `verify_log()` 和 `audit_all()`（修复 B）
3. `base.py` 中 `LOG_HMAC_KEY` 改为 `os.getenv()`（修复 C）
4. `SecureLogEntry.compose_message()` 改用 JSON 序列化（修复 D）
5. 添加 Django Admin action：选中 LogEntry → "审计 HMAC 完整性"
6. 添加管理命令：`python manage.py audit_mongo_logs`
7. ⚠️ 修复 D **是一次性迁移**——旧 SecureLogEntry 的 HMAC 值在 `compose_message` 输出变化后会全部失效，需要在 migration 中重新计算所有已有记录

### 1.4 MongoDB 旧数据迁移

由于问题 A（集合命名错误），现有 MongoDB 日志在 `poweradapter_mongo` 集合中：

```javascript
// 在 mongosh 中执行
use poweradapter_mongo
db.poweradapter_mongo.renameCollection("audit_logs")
```

---

## 2. P1 Feature：文章修订追踪（Phase 1 · 后端）

### 2.1 设计理念

**核心思路**：普通读者只看文章，深度读者才关心你改了什么。因此修订历史不应是独立页面，而是**文章底部的一个轻量折叠组件**，读者需要时展开，不需要时完全无干扰。

### 2.2 版本号方案：文章 SemVer

继承企业级软件版本号思路，针对文章语境做轻量适配：

```
v{major}.{minor}
```

| 版本变化 | 含义 | 示例 |
|---------|------|------|
| `major` 递增，minor 归零 | 重大内容变更 | v1.0 → v2.0（新增整章、重构结构） |
| `minor` 递增 | 小幅修正 | v1.0 → v1.1（错别字、措辞优化、补充说明） |

> 编辑者在保存文章时选择"大版本"或"小修订"，系统自动计算版本号。

**对比**：原方案 `revision_number: 1, 2, 3...` 只有序号，无语义。新方案一眼知道改动规模。

### 2.3 交互设计

> **读者视角**：
> - 文章正文底部一行小字：`📝 v3.2 · 5 个版本 [展开历史 ▼]`
> - 点击展开 → CSS 竖排时间线（节点+连线）
> - 每条显示：版本号、日期、编辑摘要
> - 点击某条 → 展开该版本完整内容
> - 勾选两个版本 → 显示 diff 对比
>
> **不想看的人**：只有一行 14px 灰色小字，完全无干扰。

### 2.4 节点图可视化（CSS Timeline）

**Phase 1 采用纯 CSS timeline**，零依赖，效果类似 GitHub commit 列表：

```
●──── v3.2  2026-06-21  修正错别字
│
○──── v3.1  2026-06-18  补充性能测试章节
│
●──── v2.0  2026-06-10  重构引言、新增第三章
│
○──── v1.1  2026-06-05  修正排版问题
│
●──── v1.0  2026-06-01  初始发布
```

- **实心圆** = major 版本（`v2.0`），更大更亮
- **空心圆** = minor 版本（`v3.1`），较小
- **竖线** = `--accent-deep` 绿色（devenir 配色）
- **hover** = 节点发光 + 右侧滑入详情

> 后续 Phase 2 如需分支效果，可直接替换为 Mermaid gitGraph（纯前端 JS 渲染，后端 API 不变）。

### 2.5 数据模型

```python
class PostRevision(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='revisions')
    
    # 语义化版本号
    major = models.PositiveSmallIntegerField(default=1, verbose_name="大版本")
    minor = models.PositiveSmallIntegerField(default=0, verbose_name="小修订")
    version = models.CharField(max_length=16, editable=False, verbose_name="版本号")  # "3.2"
    
    # 内容快照
    title = models.CharField(max_length=255, verbose_name="标题快照")
    desc = models.CharField(max_length=1024, blank=True, verbose_name="摘要快照")
    content = models.TextField(verbose_name="正文快照")
    slug = models.SlugField(max_length=255, verbose_name="slug快照")
    
    # 版本元信息
    editor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="编辑者"
    )
    change_type = models.CharField(
        max_length=16,
        choices=[('major', '大版本'), ('minor', '小修订')],
        verbose_name="变更类型",
    )
    edit_summary = models.CharField(max_length=200, blank=True, verbose_name="编辑摘要")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="快照时间")

    class Meta:
        unique_together = ('post', 'major', 'minor')
        ordering = ['-major', '-minor']
        verbose_name = "文章修订"
        verbose_name_plural = "文章修订"
```

**相比原版 V2GUIDE 的变化**：
- `revision_number` → `major + minor + version`（语义化版本）
- `unique_together` 改为 `('post', 'major', 'minor')`
- 新增 `change_type` 字段
- 新增 `slug` 快照（防 slug 变更后历史链接失效）

### 2.6 版本号自动计算逻辑

```python
def get_next_version(post, change_type: str) -> tuple:
    """根据变更类型计算下一个版本号"""
    last = post.revisions.order_by('-major', '-minor').first()
    if not last:
        return (1, 0)  # 首版 v1.0
    
    if change_type == 'major':
        return (last.major + 1, 0)   # v1.3 → v2.0
    else:
        return (last.major, last.minor + 1)  # v1.3 → v1.4
```

### 2.7 快照集成点

```mermaid
flowchart TD
    EDIT["PostEditView.form_valid()"]
    SAVE["Post.save()"]
    SNAP["PostRevision.objects.create()"]

    EDIT --> SAVE
    SAVE --> SNAP
    
    SNAP --> CALC["计算版本号<br/>根据 change_type 递增"]
    CALC --> CREATE["创建快照<br/>title, desc, content, slug,<br/>editor, change_type, edit_summary"]
    
    API["修订历史 API<br/>GET /api/post/{slug}/revisions/"]
    DIFF_API["Diff API<br/>GET /api/post/{slug}/diff/?from=v1.0&to=v2.0"]
    
    API --> LIST["返回版本列表 JSON<br/>{versions: [{version, date, summary, change_type}, ...]}"]
    DIFF_API --> DIFF["difflib.HtmlDiff.make_table()<br/>返回 HTML 片段"]
```

### 2.8 后端 API 设计

两个轻量 API，前端（WebStorm）通过 fetch 消费：

```python
# GET /api/post/{slug}/revisions/
# 返回版本列表
{
    "versions": [
        {"version": "3.2", "major": 3, "minor": 2, "change_type": "minor",
         "edit_summary": "修正错别字", "created_at": "2026-06-21T..."},
        {"version": "3.1", "major": 3, "minor": 1, "change_type": "minor",
         "edit_summary": "补充性能测试", "created_at": "2026-06-18T..."},
        ...
    ]
}

# GET /api/post/{slug}/diff/?from=1.0&to=2.0
# 返回 diff HTML 片段
{
    "from_version": "1.0",
    "to_version": "2.0",
    "diff_html": "<table class='diff'>...</table>"
}

# GET /api/post/{slug}/revision/v2.0/
# 返回指定版本的完整内容
{
    "version": "2.0",
    "title": "...",
    "content": "...",
    "created_at": "2026-06-10T..."
}
```

### 2.9 Diff 渲染

使用 `difflib.HtmlDiff`（Python 标准库，零依赖）：

```python
import difflib

def render_diff(old_text: str, new_text: str, from_ver: str, to_ver: str) -> str:
    """生成 HTML 格式的 side-by-side diff，以内联片段返回"""
    differ = difflib.HtmlDiff(tabsize=4, wrapcolumn=80)
    return differ.make_table(
        old_text.splitlines(),
        new_text.splitlines(),
        fromdesc=f'v{from_ver}',
        todesc=f'v{to_ver}',
        context=True,
        numlines=3,
    )
```

### 2.10 Diff 渲染

使用 `difflib.HtmlDiff`（Python 标准库，零依赖），通过 API 返回 HTML 片段，前端内联插入到时间线节点下方。

### 2.11 实施步骤（Phase 1 · 后端）

1. 创建 `PostRevision` 模型 → `python manage.py makemigrations`
2. 在 `PostForm` 中新增 `change_type` 和 `edit_summary` 字段
3. 在 `PostCreateView.form_valid()` 中自动生成 v1.0 初始快照
4. 在 `PostEditView.form_valid()` 中插入快照逻辑（`save()` 之后）
5. 实现 `get_next_version()` 版本号计算
6. 编写修订历史 API + Diff API
7. `PostAdmin` 中注册 `PostRevision` 只读 inline
8. `clear_page_caches()` 中无需额外处理（快照不缓存）

### 2.12 Phase 2 · 前端（WebStorm 完成）

- CSS timeline 组件样式（竖线+节点+动画）
- JS 交互逻辑：展开/折叠、版本选择、diff 加载
- 响应式适配（移动端 timeline 转横向）
- 可选：升级为 Mermaid gitGraph 可视化

---

## 2A. v2.1 演进：PostRevision 成为内容唯一来源

> **状态**: 规划中 · 预计 2026-06 下旬  
> **目标**: Post 退化为纯元数据容器，PostRevision 成为内容唯一数据源  
> **影响**: 模型 + 视图 + 模板 + Admin + DRF serializer · 预计 4-6h

### 2A.1 架构变化

```
v2.0 (当前)                          v2.1 (目标)
─────────────                        ────────────
Post (内容主体)                       Post (纯元数据容器)
├─ title, desc, content, slug        ├─ status, category, tag, owner
├─ status, category, tag, ...        ├─ cover, pv, uv, visibility
└─ visibility                        ├─ current_revision FK → PostRevision  ← 新增
                                     ├─ created_time, update_time
PostRevision (历史快照)               └─ ❌ 移除: title, desc, content, slug
├─ title, desc, content, slug
└─ major, minor, version, ...        PostRevision (内容唯一来源)
                                     ├─ title, desc, content, slug  ← 唯一内容
                                     ├─ major, minor, version
                                     └─ editor, change_type, ...
```

### 2A.2 路由逻辑变化

```
v2.0:  GET /post/{slug}/
       → PostDetailView.get_object()
       → Post.objects.get(slug=slug)  ← 直接从 Post 取内容
       → 模板渲染 post.title / post.content

v2.1:  GET /post/{slug}/
       → PostDetailView.get_object()
       → Post.objects.get(slug=slug)  ← Post 只有元数据
       → post.current_revision.title / .content  ← 通过 FK 取内容
       → 模板渲染 (同上，前端无感)
```

### 2A.3 好处

| 方面 | 效果 |
|------|------|
| 数据一致性 | 不会再出现 Post 内容 ≠ 最新版本内容（因为 Post 不再有内容字段） |
| 版本完整性 | 每篇文章天然有完整版本链，不存在"当前版本未归档"的漏洞 |
| 回滚能力 | 切换 `current_revision` 即可实现文章回滚（Phase 3 功能） |
| 代码简洁 | 模板不需要关心内容来源是两个表还是一个表 |

### 2A.4 实施步骤

| # | 步骤 | 文件 | 注意 |
|---|------|------|------|
| 1 | Post 加 `current_revision` FK (nullable, `related_name='current_for'`) | `Blogs/models.py` | 先 nullable，data migration 后改 not null |
| 2 | Schema migration | `makemigrations` | |
| 3 | **Data migration**: 每篇文章 `current_revision = revisions.order_by('-major','-minor').first()` | `migrations/` | 必须先有 v1.0 快照，v2.0 P1 已保证 |
| 4 | **Data migration**: 如果 latest revision 内容 ≠ Post 当前内容 → 补建一个快照 | `migrations/` | 兜底：编辑后未保存快照的边缘情况 |
| 5 | `Post.save()` 新增逻辑：更新后自动设置 `current_revision` 为最新快照 | `Blogs/models.py` | |
| 6 | 所有视图改内容来源：`post.title` → `post.current_revision.title` 等 | `Blogs/views.py` | `PostDetailView` / `PostListView` / `SearchView` 等 |
| 7 | 模板改：`{{ post.title }}` → `{{ post.current_revision.title }}` | `themes/` | 所有引用 post.title/content/desc/slug 的模板 |
| 8 | `PostAdmin` fieldsets 改为从 current_revision 代理读取 | `Blogs/admin.py` + `adminforms.py` | |
| 9 | DRF `PostSerializer` 字段来源改为 `current_revision.*` | `Blogs/serializers.py` | |
| 10 | Post 移除 `title/desc/content/slug` 列 | `models.py` + migration | 最后一步，确认所有引用已迁移 |
| 11 | PostRevision `verbose_name` 去"快照" → 改为"文章版本" | `models.py` + migration | 语义对齐 |

### 2A.5 向后兼容性

| 功能 | v2.0 行为 | v2.1 行为 |
|------|----------|----------|
| 前台文章渲染 | `{{ post.title }}` | `{{ post.current_revision.title }}` |
| 搜索 (title+content) | `Q(title__icontains=...) \| Q(content__icontains=...)` | 通过 `current_revision` 跨表查询 |
| slug 路由 | `Post.slug` | `Post.current_revision.slug` (slug 变更在快照中体现) |
| 修订 API | 不变 | 不变 (PostRevision 表结构无变化) |
| RSS Feed | `post.title` | `post.current_revision.title` |

> 核心原则：**API 不变，模板微调，前端无感**。

---

## 3. 架构与文件组织

V2 新增/修改文件：
```
Blogs/
├── models.py              # + PostRevision
├── forms.py               # + change_type, edit_summary 字段
├── views.py               # PostCreateView/PostEditView 快照逻辑
├── urls.py                # + revisions/diff API 路由
└── revisions.py           # 新建：版本计算、快照、diff 渲染工具

security/
├── mongo_client.py        # 修改：+ verify_log/audit_all, 修复集合命名
├── models.py              # 修改：compose_message 改用 JSON
└── management/
    └── commands/
        └── audit_mongo_logs.py  # 新建：审计管理命令

PowerAdapterBlogs/settings/
└── base.py                # 修改：LOG_HMAC_KEY 环境变量化
```

### 数据库迁移注意事项

| 变更 | 影响 | 处理 |
|------|------|------|
| `PostRevision` 新增表 | 无破坏性 | 普通 migration |
| `SecureLogEntry.compose_message()` 改动 | 旧 HMAC 失效 | **data migration** 重算所有记录 |
| MongoDB collection 改名 | 旧数据需迁移 | 见 §1.4 |

---

## 4. 测试清单

- [x] P0: MongoLogger 写入正确的 `audit_logs` 集合
- [x] P0: `verify_log()` 正常日志返回 True，篡改日志返回 False
- [x] P0: `audit_all()` 返回正确的统计计数
- [x] P0: `LOG_HMAC_KEY` 开发环境有硬编码兜底，生产环境必须环境变量
- [x] P1: 创建文章 → 自动生成 v1.0 快照
- [ ] P1: 编辑文章（小修订）→ 自动生成 v1.1 快照
- [ ] P1: 编辑文章（大版本）→ 自动生成 v2.0 快照
- [ ] P1: 版本列表 API 按版本号降序返回
- [ ] P1: Diff API 正确渲染中文/代码块/Markdown 差异
- [ ] P1: slug 变更后，历史快照 slug 不受影响

---

## 5. V2 明确不做的范围

| 项目 | 决策 | 原因 |
|------|------|------|
| diff 独立页面 `/post/slug/diff/` | ❌ 不做 | 改为嵌入式组件 + API |
| devenir 主题页面 | ❌ V2 不做 | 独立工作流，WebStorm 推进 |
| PostImage 模型 CRUD | ❌ 不做 | 已有但无视图，暂不启用 |
| music App 功能 | ❌ 不做 | 空壳，无计划 |
| 文章无变化跳过版本 | ❌ 不做 | 简化逻辑，编辑即保存 |
| 版本删除/回滚 | ❌ 不做 | 过度设计，Phase 3 再议 |
| 增量存储（只存 diff） | ❌ 不做 | 博客文章体积小，全量快照足够 |

---

## 6. 编码规范

### 6.1 Google Python 风格注释

本项目采用 **Google Python Style Guide** 注释风格，所有模块、类、方法、函数均需遵循。

#### 模块级 docstring

```python
"""一句话描述模块用途。

细节段落（可选），说明设计思路、限制条件、调用方注意事项等。
"""
```

#### 函数/方法 docstring

```python
def fetch_smalltable_rows(table_handle, keys, require_all_keys=False):
    """从 SmallTable 获取多行数据。

    没有该风格的函数说明（PEP 257）。细节写在后文，与参数之间空一行。

    Args:
        table_handle: open smalltable.Table 实例。
        keys: 要获取数据的字符串键序列。
        require_all_keys: 如果为 True，键缺失时抛出 KeyError。

    Returns:
        一个 dict，将键映射到对应的 table_handle 数据。
        如果 require_all_keys 为 False，缺失键不出现。

    Raises:
        IOError: 如果 table_handle 不可读。
    """
```

#### 类 docstring

```python
class SampleClass:
    """类的概要说明。

    更详细的描述（可选）。可包含使用示例：

    Example:
        >>> obj = SampleClass(123)
        >>> obj.public_method()
        'hello'

    Attributes:
        likes_spam: 布尔值，指示是否喜欢午餐肉。
        eggs: 统计已计数鸡蛋的整数。
    """

    def __init__(self, likes_spam=False):
        """初始化 SampleClass。

        Args:
            likes_spam: 初始化 likes_spam 属性。
        """
```

#### 管理命令 docstring

```python
"""
管理命令简要说明。
用法：python manage.py command_name [--option VALUE]
"""
```

#### 关键规则

| 规则 | 说明 |
|------|------|
| 第一行 | `"""` 后紧跟概要，不空行 |
| 空行 | 概要段落后空一行再写详细描述 |
| Args | 参数名 + 冒号 + 空格 + 类型/描述 |
| Returns | 返回值类型和含义，多类型用 `or` 分隔 |
| Raises | 每个异常一行，注明触发条件 |
| 中文 | 当前项目使用中文描述（便于团队理解） |

#### 示例对照

```python
# ✅ Google 风格
def _word_wrap(text: str, width: int = 80) -> str:
    """按单词边界对文本换行，提升行级 diff 颗粒度。

    规律：
    - Markdown 结构型行保持原样不换行
    - 普通段落按 width 个字符在单词边界处强制换行

    Args:
        text: 原始文本内容。
        width: 每行最大字符数，默认 80。

    Returns:
        换行后的文本字符串。
    """
```

```python
# ❌ 旧风格（需要逐步迁移）
def render_diff(old_text, new_text, from_ver, to_ver):
    """生成 HTML 格式 side-by-side diff
    使用 difflib.HtmlDiff（Python 标准库，零依赖）
    """
```

### 6.2 Pylint 配置

#### 安装

```bash
pip install pylint pylint-django
```

#### `.pylintrc` 配置文件

项目根目录创建 `.pylintrc`：

```ini
[MASTER]
# 使用 pylint-django 插件
load-plugins=pylint_django

# Django 项目：settings 模块
django-settings-module=PowerAdapterBlogs.settings.develop

# 忽略虚拟环境和缓存
ignore=.venv,venv,node_modules,__pycache__,migrations

# 并行检查（加速）
jobs=0

[MESSAGES CONTROL]
# 禁用的检查项（Django 项目常见豁免）
disable=
    C0114,  # missing-module-docstring
    C0115,  # missing-class-docstring
    C0116,  # missing-function-docstring（改为手动审查）
    R0903,  # too-few-public-methods（Django views/models 常见）
    R0801,  # duplicate-code（暂时关闭，后续分阶段开启）
    W0212,  # protected-access（Django _meta 常用）
    E1101,  # no-member（Django ORM 动态属性，pylint-django 已处理大部分）

[FORMAT]
# 每行最大字符数
max-line-length=100

# 缩进
indent-string='    '

[DESIGN]
# 参数数量警告阈值
max-args=8

# 方法/函数行数警告
max-locals=20

[BASIC]
# 变量名风格
good-names=i,j,k,ex,_,pk,id,url,db,ip,ok

# 类属性名
class-attribute-naming-style=any

# Django 的 objects 不应告警
const-naming-style=any
```

#### 运行方式

```bash
# 全项目检查
pylint Blogs/ security/ accounts/ comment/ config/

# 单文件检查
pylint Blogs/views.py

# 仅显示错误（跳过警告和约定）
pylint --errors-only Blogs/

# Git pre-commit hook 集成（可选）
# pylint --fail-under=8.0 Blogs/ security/
```

#### Google 风格兼容说明

| pylint 规则 | 与 Google 风格的关系 |
|------------|---------------------|
| `C0116` (missing-function-docstring) | 禁用以手动审查，Google 风格要求全部函数有 docstring |
| `R0903` (too-few-public-methods) | Django CBV / Model 常见，豁免 |
| `max-line-length=100` | Google 风格建议 80，本项目放宽到 100（Django 惯例） |
| `good-names` | `pk` `id` `db` `ip` 是 Django 项目中合法的短变量名 |

#### 迭代迁移计划

现有代码不要求一次性全部符合 Google 风格，按以下优先级逐步迁移：

| 优先级 | 目标 | 触发条件 |
|--------|------|---------|
| **P0** | 新建文件严格遵循 Google 风格 | 创建新模块/命令/视图时 |
| **P1** | 修改文件时顺带更新 docstring | 修改已有文件时 |
| **P2** | 全局 pylint 检查通过 ≥8.0 分 | 特性冻结前统一处理 |
| **P3** | 启用 `C0116` 严格检查 | P2 完成后 |

---

## 8. 前端效果库参考

> 候选库，尚未引入项目。记录于此供未来参考，避免遗忘。

### 8.1 glitch-text-effect · 已移除 ❌

| 项目 | 信息 |
|------|------|
| **原版本** | `1.0.2` (2025-08-06) |
| **移除原因** | ① overlay 遮罩方案与项目风格不统一 ② `glitch()` 忽略 `trigger` 参数 ③ 缺失 @keyframes 注入 ④ 效果对浏览器性能压力大 |
| **替换者** | 自研 rAF 批处理 scramble（§8.2），零外部依赖 |
| **移除日期** | 2026-06-22，已从 `package.json` 卸载 |

### 8.2 Post Detail Scramble · rAF 批处理内联解密 ✅ 已集成

| 项目 | 信息 |
|------|------|
| **风格参考** | KAMITSUBAKI STORY R&D DIV (`shuffle-text` + `<span class="shuffle trigger">`) |
| **实现方式** | 自研 `scrambleBlock()` — rAF 批处理 + 单文本节点更新，零 DOM 膨胀 |
| **触发方式** | IntersectionObserver，滚动到视口才开始解密 |
| **字符集** | `CHAR_POOL = '{}[]()<>;:=!&|/\\#@$%^*+-_0123456789abcdef<>?`~'`（代码符号风） |
| **优化** | ① rAF 批处理替代 n 个 `setTimeout`（1000 字符块从 ~3000 个 timer → 1 个 rAF loop） ② 单文本节点替代 n 个 `<span>`（500 字文章从 2500+ 个 span → 零） ③ `fastResolve()` 快速滚动即时解密 |

**核心算法**：每个文本块保持单文本节点，`requestAnimationFrame` 每帧揭示 10 个字符，未揭示部分每帧重新随机化。块间 stagger 50ms。全部揭示后恢复 `innerHTML`（保留 Markdown 格式化）。

**快速滚动保护**：`exitObserver` 监听文章容器离开视口 → `fastResolve()` 立即恢复所有进行中的块到原始 `innerHTML` + flash 动画。不阻塞用户浏览。

**性能对比**：

| 指标 | 旧方案（per-char spans） | 新方案（rAF batch） |
|------|--------------------------|---------------------|
| DOM 节点 | 2500+ spans/文章 | 1 text node/block |
| 定时器 | ~2500 setTimeout | 1 rAF loop |
| CSS 动画 | 每帧 2000+ 元素 jitter | 仅 flash 完成时 |
| 10 块文章完成时间 | 2-5 秒 | ~1.2 秒 |
| 快速滚动 | 卡顿，动画继续跑 | 即时 resolve |

**CSS**：`.scramble-active` (opacity 0.82) / `.scramble-done` (decrypt-flash 0.4s)。定义于 `blog.css`。

```javascript
// 标题 — single-block rAF scramble
scrambleBlock(titleEl, CHAR_POOL, 0);

// 正文 — per-block rAF scramble + fast-scroll guard
blocks.forEach(function(block, idx) {
    scrambleBlock(block, CHAR_POOL, idx * BLOCK_STAGGER);
});

// 文章离开视口 → 即时解密所有块
exitObserver: if (!isIntersecting && activeJobs.length > 0) fastResolve();
```

### 8.2 powerglitch · 图像故障效果

| 项目 | 信息 |
|------|------|
| **用途** | `<img>` 元素的 RGB 色散、抖动、切片、颜色反转等复杂 glitch 动画 |
| **体积** | ~5KB (min + gzip ~2KB) |
| **许可证** | MIT |
| **仓库** | `github.com/7PH/powerglitch` |
| **适用场景** | 文章封面图、board visual SVG→raster 化后的 glitch、未来可能的图片画廊 |
| **注意** | 纯 Canvas 渲染，需要 `<img>` 源。不适合当前 boards 的 CSS 视觉区（SVG/波形/代码行）。 |
| **引入时机** | 等有真正的图像内容需要 glitch 时再 `npm install powerglitch` |

```javascript
// 示例用法（未来图片 glitch）
import { PowerGlitch } from 'powerglitch';
PowerGlitch.glitch('.article-cover', {
    playMode: 'hover',
    glitchTimeSpan: false,
    shake: { amplitudeX: 4, amplitudeY: 2 },
    slice: { count: 6, velocity: 12 },
});
```

---

## 7. 已完成修复记录（2026-06-22）

> 详细记录见 `CHANGELOG.md`，此处仅做架构级概述。

### 7.1 双后台入口权限分离

`/super_admin/` 和 `/dashboard/` 两个入口的权限模型完全解耦：

| 入口 | 需要 | 反向解析 |
|------|------|---------|
| `/super_admin/` | `is_staff`（Django 默认） | `reverse("admin:index")` |
| `/dashboard/` | `is_dashboard_user`（CustomSite 自定义） | `reverse("cus_admin:index")` |

**关键修复**：
- `CustomSite.has_permission()` 重写为 `is_dashboard_user` 检查（原继承 `is_staff`）
- 登录 `NoReverseMatch` 修复：AdminSite URL 必须用 `namespace:name` 反解（`cus_admin:index`），不能用外层 `path()` 的 `name=`
- `DashboardAdminMixin`（`base_admin.py`）：7 个方法统一基于 `is_dashboard_user` 授权，覆盖权限检查 + queryset（dashboard 用户看全量数据，不受 owner 过滤）

### 7.2 纵深防御（4 层）

```
Layer1: Admin UI 守卫 (has_change/delete)
Layer2: Admin save_related M2M 拦截（groups/user_permissions）
Layer3: Model.save() 字段回滚（is_superuser/is_staff/is_dashboard_user）
Layer4: pre_save/pre_delete 信号拦截（LogEntry/SecureLogEntry）
```

**新增文件**：`accounts/thread_local.py` + `accounts/middleware.py` RequestUserMiddleware

### 7.3 superuser 保护

dashboard 用户不能编辑 superuser 账号（双重保险）：
- `has_change_permission(obj=...)`：目标为 superuser 且请求者非 superuser → 直接拒绝
- `get_readonly_fields(obj=...)`：同上条件 → 全字段只读
