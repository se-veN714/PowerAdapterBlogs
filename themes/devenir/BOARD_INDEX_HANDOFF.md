# Board Index 前端分支交接

> **文档权重**：80（`codex/board-index-k3` 前端实施边界；架构服从 V2 与 boards 文档）
> **状态**：已规划，尚未实现
> **更新**：2026-07-27

## 1. 目标

为每个代码内已注册的 Board 制作独立 Index 视觉页面。Board 创建仍只允许 superuser，且“新增 Board 等于新增前端代码”；本分支不实现动态页面生成器。

## 2. K3 允许修改

- `themes/devenir/templates/pages/boards/` 下的新模板与局部模板。
- `themes/devenir/static/css/` 下 Board Index 专用样式。
- `themes/devenir/static/js/` 下仅服务展示效果的脚本。
- 本交接文档中的视觉说明、人工验收记录和静态资源清单。

K3 不得修改 Python、Model、Migration、权限 Policy、URLConf、Form、Admin、API、测试数据或 `base.html` 全局导航。需要新上下文字段时，只在本文档登记契约需求，由后端分支实现。

## 3. 后端上下文契约

前端按以下只读变量设计；未提供的数据必须有安全空态，不得在模板中查询权限：

| 变量 | 含义 |
|---|---|
| `board` | 当前 active Board；可使用 `slug/name/description/glitch_color/keywords_list` |
| `post_list` | 当前 Board 对应分类下、已通过 Policy 筛选的文章 |
| `featured_post` | 可空的首要展示文章 |
| `recent_posts` | 可空的近期文章列表 |
| `membership_role` | 可空的当前用户板块角色显示值；只用于展示，不作为授权依据 |
| `can_create_post` | 后端 Policy 计算的布尔值；模板只决定是否显示入口 |

## 4. 视觉与工程约束

- 延续 Devenir CRT、Editorial、非对称网格和板块 `glitch_color`，视觉效果优先。
- 每个 Board 可以有独立模板/样式，但共享可访问性、移动端无横向溢出和 reduced-motion 基线。
- 复用现有文章卡片或局部模板时，不改变其可见性与编辑权限判断。
- 不引入 SPA、前端路由或 JSON 驱动重写；继续使用 Django Template + htmx HDA。
- 首轮只提交静态视觉与空态；导航、路由和真实 QuerySet 由后端集成阶段接入。

## 5. 人工验收

- [ ] 匿名用户只能看到公开已发布文章。
- [ ] 没有文章、没有特色文章和没有 Membership 时页面完整可用。
- [ ] 390px、768px、1280px 无横向溢出，交互目标不小于 44px。
- [ ] reduced-motion 下没有持续扫描、闪烁或位移动画。
- [ ] K3 分支 `git diff` 不包含任何 `.py` 或 migration 文件。
