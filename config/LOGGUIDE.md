# Config App — 日志指南

> 配套：[根目录 LOGGUIDE.md](../LOGGUIDE.md)

---

## 职责边界

Config app 管理博客站点的全局配置项（站点标题、副标题、SEO 元数据、社交链接等）。通常只有站长在 Django Admin 中修改，操作频率极低但影响面大。

---

## 日志点清单

### A. 站点配置修改

| 时机 | 级别 | 内容 |
|------|------|------|
| 配置修改 | INFO | config_key, old_value (截断), new_value (截断), operator_id |
| 配置创建 | INFO | config_key, value (截断), operator_id |
| 配置删除 | INFO | config_key, operator_id |

```python
# 在 admin.py 的 save_model 中
def save_model(self, request, obj, form, change):
    if change:
        old = Config.objects.get(pk=obj.pk)
        logger.info(f"Config 修改: key={obj.key} operator={request.user.id} "
                    f"old={str(old.value)[:50]} new={str(obj.value)[:50]}")
    else:
        logger.info(f"Config 创建: key={obj.key} operator={request.user.id}")
    super().save_model(request, obj, form, change)
```

> 值截断到 50 字符 — 防止配置内容过长。DMeta/SEO 描述字段可能很长。

### B. 缓存失效

Config 修改后通常需要清除相关缓存：

```python
def save_model(self, request, obj, form, change):
    super().save_model(request, obj, form, change)
    # 清除站点配置缓存
    try:
        cache.delete("site_config")
    except Exception as e:
        logger.warning(f"Config 缓存清除失败: key={obj.key} error={e}")
```

---

## 不打日志的位置 (config)

| 位置 | 原因 |
|------|------|
| 每次请求读取 Config | 高频读，用缓存即可 |
| Config 模型 save() | Admin 层已覆盖 |
