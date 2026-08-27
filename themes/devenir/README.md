# Devenir Theme

> **文档权重**：50（主题快速入口；实现细节以 `DEVELOPMENT.md` 为准）

当前启用的 Django Template + htmx 主题。详细架构、模板和静态资源说明见 [`DEVELOPMENT.md`](DEVELOPMENT.md)。

PostList 视觉重构的长期规范记录在本主题文档与项目 V2 指南中；本地 HANDOFF 仅用于 Agent 临时交接，不纳入 Git。参考图见 [`sample/postlist-concept-image2.png`](sample/postlist-concept-image2.png)。

## 视觉语言速览

Devenir 以连续近黑空间、CRT 扫描纹理、Editorial 信息层级和等宽遥测文字为骨架。错误页重构进一步确立“透明主体融合 + Board 信号色 + 短促故障动效”的表达：视觉主体可以越过传统分栏形成空间关系，但信息仍需清晰、可访问并在无 JavaScript 时成立。

- General 使用青绿色信号；Skateboard、Music、Coding 使用各自 Board 色与语义词汇。
- 动效只用于状态和气氛，必须支持 reduced-motion，不能代替文字反馈。
- 最终 WebP/SVG/Logo 属于运行时依赖并随仓库交付；PNG/PSD 源稿、AI 中间稿和用户媒体不跟踪。
- DEBUG 环境可通过 `/_errors/<variant>/<status_code>/` 以真实状态码预览错误页；生产关闭。当前 variant 为 `general`、`skateboard`、`music`、`coding`。
