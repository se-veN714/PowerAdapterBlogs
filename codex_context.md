# PowerAdapterBlogs — 会话上下文 (2026-06-22)

## 当前状态总览

| 项目 | 状态 |
|------|------|
| P0 MongoDB 日志修复 (4/4) | ✅ 已完成 |
| P1 文章修订追踪 Phase 1 后端 | ✅ 已完成 |
| P2 文章修订追踪 Phase 2 前端 | WebStorm 推进中 |
| v2.1 Post→元数据容器+PostRevision唯一内容源 | 📋 下一项（11步/4-6h） |

## 核心架构决策

### Post vs PostRevision 关系
- **v2.0 当前**：Post 是内容主体，PostRevision 是编辑时自动存档的快照
- **版本顺序**：`(major, minor)` 语义化版本号排序，**不是链式结构**（无 parent FK）
- **v2.1 演进后**：Post 退化为纯元数据（删 title/desc/content/slug），PostRevision 成内容唯一来源
- **路由逻辑 v2.1**：`post.current_revision.title` 替代 `post.title`，模板微调，前端无感

### 版本号规则
- `major` 递增 → minor 归零（大版本，如 1.0→2.0）
- `minor` 递增（小修订，如 1.0→1.1）
- 编辑者保存时选择 change_type，系统自动计算版本号

### visibility 权限矩阵
| 用户类型 | PUBLIC | STAFF_ONLY |
|---------|--------|------------|
| 匿名 | ✅ | 404 |
| 普通登录 | ✅ | 404 |
| dashboard_user | ✅ | ✅ |
| staff | ✅ | ✅ |
| superuser | ✅ | ✅ |

## 关键文件索引

| 文件 | 作用 |
|------|------|
| `Blogs/models.py` | Post + PostRevision + PostVisit + Category + Tag + PostImage |
| `Blogs/revisions.py` | 版本号计算、快照创建、diff渲染、权限判断 |
| `Blogs/views.py` | PostCreateView(创建+v1.0快照)、PostEditView(编辑+快照)、3个修订API |
| `Blogs/urls.py` | 15个URL路由含3个修订API端点 |
| `Blogs/admin.py` | PostAdmin + PostRevisionInline(只读) |
| `Blogs/DEVELOPMENT.md` | 完整架构文档(ER图/数据流/路由表/缓存/v2.1路线) |
| `V2GUIDE.md` | V2开发指南(P0/P1/P2/v2.1) |
| `security/mongo_client.py` | MongoDB日志客户端(P0已修复) |
| `security/models.py` | SecureLogEntry(P0已修复compose_message→JSON) |

## 修订 API 端点
```
GET  /api/post/{slug}/revisions/     → 版本列表JSON
GET  /api/post/{slug}/revision/v2.0/ → 指定版本完整内容
GET  /api/post/{slug}/diff/?from=1.0&to=2.0 → diff HTML片段
```

## 测试数据生成
```
python manage.py bump_versions --count 10          # 对最近10篇文章做小修改+minor版本
python manage.py bump_versions --count 10 --dry-run # 预览模式
```

## 下一步
v2.1 演进 — Post 加 current_revision FK，内容字段迁移到 PostRevision（详见 V2GUIDE.md §2A）
