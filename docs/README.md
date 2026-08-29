# PowerAdapterBlogs 文档中心

> **文档权重**：81（项目文档导航；具体决策服从所链接的上位与专项文档）

根目录只保留项目入口、当前版本路线和全局开发说明；跨模块专项规范统一放在本目录。各 App 与主题的实现文档继续与代码放在一起。

## 全局入口

| 文档 | 权重 | 用途 |
|---|---:|---|
| [V2GUIDE.md](../V2GUIDE.md) | 100 | 当前版本、全局架构和路线决策 |
| [DEVELOPMENT.md](../DEVELOPMENT.md) | 82 | 项目结构、路由、技术栈与开发入口 |
| [CHANGELOG.md](../CHANGELOG.md) | 60 | 历史变更记录 |

## 专项指南

| 文档 | 权重 | 用途 |
|---|---:|---|
| [DOCUMENTATION_GUIDE.md](guides/DOCUMENTATION_GUIDE.md) | 99 | 文档阅读顺序、作用域和冲突规则 |
| [CODING_GUIDE.md](guides/CODING_GUIDE.md) | 95 | Python/Django 编码硬约束 |
| [GIT_AGENT_WORKFLOW_GUIDE.md](guides/GIT_AGENT_WORKFLOW_GUIDE.md) | 89 | Git 分支、worktree、多 Agent 交接、ref 快照与事故恢复流程 |
| [BLOG_FOUNDATION_GUIDE.md](guides/BLOG_FOUNDATION_GUIDE.md) | 87 | Profile、账号设置、About、隐私、归档、Feed 与站点元数据实施路线 |
| [SECURITY_ASSESSMENT_GUIDE.md](guides/SECURITY_ASSESSMENT_GUIDE.md) | 90 | 评论实名门禁、投诉举报闭环、六个月日志留存及人工边界 |
| [DJANGO_LTS_UPGRADE.md](guides/DJANGO_LTS_UPGRADE.md) | 86 | Django 5.2 LTS 升级记录与能力边界 |
| [LOGGUIDE.md](guides/LOGGUIDE.md) | 75 | 全项目日志主规范 |

## 模块文档

模块级 `DEVELOPMENT.md`、`LOGGUIDE.md` 和专项交接文档保留在对应 App 或主题目录。阅读全局指南后，再进入目标模块查看局部约束。

个人学习计划、Agent 上下文和本地 Git 工作流不属于仓库文档，通过 `.gitignore` 单独保留。
