# PowerAdapterBlogs 文档权重与阅读顺序

> **文档权重**：99（文档路由规则；仅次于 `V2GUIDE.md`）
> **更新**：2026-07-13
> **用途**：帮助开发者与 Agent 判断阅读顺序、文档作用域和冲突处理方式。

## 1. 权重含义

文档权重范围为 `0–100`，数值越高，越优先作为项目当前决策依据。`V2GUIDE.md` 固定为最高权重 `100`。

权重不表示低权重文档无效：旧文档仍可作为历史基线和局部实现参考，但不得覆盖更高权重文档中已经更新的架构、版本或安全决策。

## 2. 冲突处理顺序

1. 当前用户在会话中的明确指令。
2. 已运行代码、数据库约束与自动化测试所证明的事实。
3. 文档权重更高者。
4. 同权重时，日期更新者优先。
5. 高权重文档未覆盖的细节，由作用域更窄的 App/主题专项文档补充。

规划文档不得被当作已实现事实；即使权重较高，也必须读取其“状态”字段。

## 3. 推荐阅读顺序

| 权重 | 文档 | 作用 |
|---:|---|---|
| 100 | `V2GUIDE.md` | 当前版本、全局架构和路线决策 |
| 99 | `DOCUMENTATION_GUIDE.md` | 文档路由和冲突规则 |
| 95 | `CODING_GUIDE.md` | Python/Django 编码硬约束 |
| 92 | `codex_context.md`（本地） | 当前 Agent 交接快照，不覆盖 V2 决策 |
| 90 | `accounts/PERMISSIONS_GUIDE.md` | 当前 Board Scope 权限主设计与 `accounts_linear` |
| 88 | `accounts/SECURITY_ROADMAP.md` | v2.5+ MFA 与密钥生命周期规划 |
| 85 | 各 App `DEVELOPMENT.md` | 对应模块当前实现与 TODO |
| 82 | 根目录 `DEVELOPMENT.md` | 项目结构与通用开发入口 |
| 80 | `GITGUIDE.md`（本地） | Git 操作范围内的提交规范 |
| 78 | `themes/devenir/DEVELOPMENT.md` | 当前主题实现细节 |
| 75 | 根目录 `LOGGUIDE.md` | 全项目日志规范 |
| 70 | 各 App `LOGGUIDE.md` | 模块日志细节 |
| 60 | `CHANGELOG.md` | 历史变更记录，不代表当前设计 |
| 50 | `README.md`、主题 README | 项目介绍与快速入口 |
| 40 | `themes/devenir/Project_context.md` | 主题历史上下文，冲突时让位于主题 DEVELOPMENT |
| 30 | `music/*` | 已停用空壳模块的历史参考 |

## 4. Agent 最小阅读集

开始全局任务时至少阅读：

1. `V2GUIDE.md`
2. `CODING_GUIDE.md`
3. 目标 App 的 `DEVELOPMENT.md`
4. 与任务直接相关的专项 Guide
5. 如涉及日志，再阅读根目录与目标 App 的 `LOGGUIDE.md`

不得仅凭 `README.md`、`CHANGELOG.md` 或旧 `Project_context.md` 推断当前架构。
