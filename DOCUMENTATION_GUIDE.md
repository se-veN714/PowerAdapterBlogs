# PowerAdapterBlogs 文档治理与阅读顺序

> **文档权重**：95（文档权重、阅读顺序与冲突处理总则；不覆盖 V2 当前架构决策）
> **更新**：2026-07-29

## 1. Agent 阅读顺序

1. `V2GUIDE.md`（100）：当前版本、跨 App 架构、路线和用户已确认决策的唯一最高依据。
2. `DOCUMENTATION_GUIDE.md`（95）：文档权重、冲突处理和维护规则。
3. 专项安全/架构与运维 Guide（86–90）：例如 `deploy/mtls/README.md`（90）、`docs/guides/GIT_AGENT_WORKFLOW_GUIDE.md`（89，本地、git-ignored）、`accounts/SECURITY_ROADMAP.md`（88）。
4. App `DEVELOPMENT.md`（85）：当前模块实现、测试入口、模型和 TODO。
5. 根 `DEVELOPMENT.md`（82）与专项设计文档（78–84）：开发入口、部署清单和受限任务边界；Board 展示/参与边界以 `docs/guides/BOARD_CONTENT_VISIBILITY_GUIDE.md`（84，本地、git-ignored）为准。
6. `CHANGELOG.md`（60）：历史记录，不覆盖当前代码和高权重文档。
7. README、旧方案、备份和归档材料：仅作背景；与上位文档冲突时不得作为当前实现依据。

## 2. 冲突处理

按以下顺序裁决：用户当前明确指令 → 代码/迁移/测试事实 → 较高文档权重 → 较新更新时间。规划必须标注“未实现”，历史完成记录不得冒充当前运行时行为。

权重表示 Agent 采信优先级，不是 TODO 严重度、功能优先级或代码质量评分。项目最高权重必须唯一；未经用户确认不得调整 `V2GUIDE.md` 的最高地位。

## 3. 更新规则

- 跨 App 决策先更新 V2，再同步专项 Guide、App 文档和 CHANGELOG。
- 稳定实现的细节下移到所属 App 文档；V2 只保留完成结论、边界和链接。
- 新增文档必须声明权重、职责和更新时间，并加入根 `DEVELOPMENT.md` 索引。
- TODO 使用红/黄/绿严重度，分别表示安全/一致性、重要设计债务、可选优化。
- Mermaid 用于三个及以上组件之间的权限、状态或请求流程。
- `.venv`、依赖包、构建产物、Agent 临时上下文和归档副本不纳入项目文档权重体系。

## 4. Agent 临时交接材料不得跟踪

HANDOFF、一次性 Agent 上下文、线程移交说明和仅服务某个 worktree 的任务快照属于本地协作材料，不是项目开发文档，不得加入 Git。

- 新建时统一放入 `.local/handoffs/<task>/`；若工具必须把文件放在源码附近，文件名必须包含 `HANDOFF`，由根 `.gitignore` 的 `**/*HANDOFF*.md` / `**/*handoff*.md` 规则排除。
- 临时材料不声明项目文档权重，不加入根 `DEVELOPMENT.md` 或 `docs/README.md` 索引，也不能被已跟踪文档作为唯一依据链接。
- 可长期复用的架构结论、权限边界、上下文契约和验收标准必须回写 `V2GUIDE.md`、专项 Guide 或对应 App `DEVELOPMENT.md`；HANDOFF 只引用这些正式来源。
- 需要长期纳入仓库的内容不得继续使用 `HANDOFF` 命名，应改写为职责明确的 `*_GUIDE.md` 或 `DEVELOPMENT.md`，补充权重后按正常文档流程评审。
- 提交前执行 `git ls-files | rg -i "handoff"`，结果必须为空；新文件另用 `git check-ignore -v <path>` 确认命中忽略规则。
- 若文件已误跟踪，使用 `git rm --cached -- <path>` 只移除索引并保留本地文件，同时清理仓库文档中的死链。

## 5. Agent 分支交接规范

- 跨 Agent 交接必须先遵守 `V2GUIDE.md` 的强制规则：先向用户说明 Agent、范围、已提交基线 SHA、新分支名、worktree 路径和禁止修改范围，得到明确同意后才由主 Agent 创建新分支。
- 接收任务的 Agent 不拥有 branch/ref/worktree 生命周期权限；它只使用已经分配的 worktree。需要调整基线、重建分支或新增 worktree 时，必须返回主 Agent 并重新取得用户确认。
- 本地执行清单与事故恢复流程放在 `docs/guides/GIT_AGENT_WORKFLOW_GUIDE.md`（89，git-ignored）；高权重的授权边界只以 `V2GUIDE.md` 和本节为准，本地 Guide 不能放宽它。
- Git 快照、临时恢复记录和 Agent 交接状态统一放入 `.local/git-safety/` 或 `.local/handoffs/`，不得进入仓库。
