# Blogs App — 日志指南

> 配套：[根目录 LOGGUIDE.md](../LOGGUIDE.md)

---

## 职责边界

Blogs 是项目核心业务模块：文章 CRUD、分类/标签管理、PV/UV 统计、全文搜索、REST API、站点地图。**任何对 Post/Category/Tag 的写操作都应该打 INFO 日志。**

---

## 日志点清单

### A. 视图层 (views.py)

#### A1. PostCreateView — 文章创建

| 时机 | 级别 | 内容 |
|------|------|------|
| `form_valid()` | INFO | 创建成功：post_id, slug, user_id, category |
| `form_invalid()` | WARNING | 表单验证失败：user_id, errors |

```python
def form_valid(self, form):
    response = super().form_valid(form)
    logger.info(f"Post 创建: post_id={self.object.id} slug={self.object.slug} "
                f"user={self.request.user.id} category_id={self.object.category_id}")
    return response

def form_invalid(self, form):
    logger.warning(f"Post 创建表单失败: user={self.request.user.id} "
                   f"errors={form.errors}")
    return super().form_invalid(form)
```

#### A2. PostEditView — 文章编辑

| 时机 | 级别 | 内容 |
|------|------|------|
| `form_valid()` | INFO | 编辑成功：post_id, slug, 变更字段（对比新旧） |
| `form_invalid()` | WARNING | 表单验证失败：post_id, user_id, errors |

```python
def form_valid(self, form):
    old_title = self.object.title
    response = super().form_valid(form)
    changed = []
    if old_title != self.object.title:
        changed.append("title")
    if form.cleaned_data.get("content") != self.object.content:
        changed.append("content")
    logger.info(f"Post 编辑: post_id={self.object.id} slug={self.object.slug} "
                f"user={self.request.user.id} changed={changed}")
    return response
```

> 注意：V2 P1 完成后，此处还应该记录版本快照是否成功创建。

#### A3. PostDetailView — 文章详情

| 时机 | 级别 | 内容 |
|------|------|------|
| PV/UV 写入异常 | ERROR | 访问统计写入失败：post_id, uid, visit_type |
| 缓存操作异常 | WARNING | 缓存清除/写入失败：cache_key |

```python
# 在 handle_visit() 中
try:
    PostVisit.objects.get_or_create(...)
except Exception as e:
    logger.exception(f"PostVisit 写入失败: post_id={self.object.id} "
                     f"uid={self.request.uid}")
```

> 注意：PV/UV 写入本身是高频操作，**不要在正常情况下打日志**，只记录异常。

#### A4. PostDeleteView — 文章删除（如有）

| 时机 | 级别 | 内容 |
|------|------|------|
| `delete()` | INFO | post_id, slug, user_id, title（软删除需标记） |

#### A5. post_img_upload — 图片上传

| 时机 | 级别 | 内容 |
|------|------|------|
| 上传成功 | INFO | filename, size, user_id |
| 上传失败 | ERROR | filename, error |

```python
# 上传成功
logger.info(f"图片上传: file={filename} size={size} user={request.user.id}")

# 上传失败
logger.error(f"图片上传失败: file={filename} user={request.user.id} error={e}")
```

#### A6. Category/Tag CRUD

| 时机 | 级别 | 内容 |
|------|------|------|
| 创建 | INFO | category_id/name 或 tag_id/name, user_id |
| 编辑 | INFO | id, name, changed_fields |
| 删除 | INFO | id, name, user_id |

### B. REST API (apis.py)

| ViewSet 方法 | 级别 | 内容 |
|-------------|------|------|
| `create()` | INFO | Post 创建：post_id, slug, user |
| `update()` / `partial_update()` | INFO | Post 编辑：post_id, changed_fields |
| `destroy()` | INFO | Post 删除：post_id, slug |
| `create/update/destroy()` (异常) | ERROR | 操作类型, post_id, error |

```python
class PostViewSet(ModelViewSet):
    def perform_create(self, serializer):
        instance = serializer.save()
        logger.info(f"API Post 创建: post_id={instance.id} slug={instance.slug} "
                    f"user={self.request.user.id}")

    def perform_destroy(self, instance):
        logger.info(f"API Post 删除: post_id={instance.id} slug={instance.slug} "
                    f"user={self.request.user.id}")
        instance.delete()
```

### C. 模型层 (models.py)

#### C1. Post.save()

自动生成 slug 时记录（仅在 slug 为空时触发）：

```python
def save(self, *args, **kwargs):
    if not self.slug:
        generated = generate_slug(self.title)
        self.slug = generated
        # slug 为空时记录（说明是新创建的）
```

> Post.save() 本身不需要额外日志 — slug 生成已在视图层覆盖。

#### C2. PostVisit — 不打日志

每一篇文章的每次访问都触发 `PostVisit` 写入。**绝不在 PostVisit 上打日志** — 这是日志量爆炸的第一大杀手。

### D. 管理命令 (management/commands/)

#### D1. generate_posts

```python
logger.info(f"generate_posts 开始: count={count} category_id={cat_id}")
# ... 生成逻辑 ...
logger.info(f"generate_posts 完成: created={success_count} failed={fail_count}")
```

#### D2. init_slug

```python
logger.info(f"init_slug 开始: posts_without_slug={count}")
# ... 处理逻辑 ...
logger.info(f"init_slug 完成: fixed={fixed_count}")
```

### E. 缓存清除

`clear_page_caches()` 被多处调用，本身不需日志。但如果清除失败：

```python
try:
    clear_page_caches()
except Exception as e:
    logger.warning(f"缓存清除失败: keys={cache_keys} error={e}")
```

### F. 中间件 (middleware/user_id.py)

| 时机 | 级别 | 内容 |
|------|------|------|
| UUID 生成 | DEBUG | visitor_id（仅调试时） |
| Cookie 设置异常 | WARNING | visitor_id, error |

> 中间件主流程不要打日志 — 每个请求都走这里。

---

## 不打日志的位置 (Blogs)

| 位置 | 原因 |
|------|------|
| `PostDetailView.get_context_data()` | 读操作，每次请求都触发 |
| `IndexView.get_context_data()` | 读操作 |
| `PostListView.get_queryset()` | 读操作 |
| `SearchView` 正常搜索 | 读操作（搜索无结果是正常现象） |
| `PostVisit` 正常读写 | 高频写，日志爆炸 |
| 模板标签 (`md_extras.py`) | 渲染时调用 |
| `Post.save()` 常规更新 | 视图层已覆盖（除非有特殊副作用） |
| `Category.save()` / `Tag.save()` | 视图层已覆盖 |
