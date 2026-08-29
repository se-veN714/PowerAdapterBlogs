# PowerAdapterBlogs

> **文档权重**：50（项目介绍；实现与路线以高权重文档为准）

这是一个由个人长期运营的多板块站点，也是我持续学习和实践 Django 的项目。

## 项目定位与适用边界

PowerAdapterBlogs 不是轻量级博客模板。它采用 Django 单体架构，但包含多个拥有独立视觉语言、数据模型、CRUD、媒体流程和权限规则的内容板块，同时覆盖账户、MFA、板块准入、审计、举报、邮件验证、异步任务、媒体处理与生产部署。“单体”表示交付边界集中，不表示功能简单或运维成本低。

这个项目主要面向与我有类似需求的使用者：希望在同一个个人站点中长期经营多个异质内容场域，并且需要完整的管理、权限、安全与部署能力。如果只需要一个开箱即用的文章列表、少量静态页面或最低成本的容器部署，这个项目通常并不合适。

前端采用 Django Template + htmx 驱动的 Devenir 主题。其视觉语言以连续暗色空间、CRT 扫描纹理、Editorial 排版和板块信号色为基础；重要视觉页面可使用透明主体融合与受控 glitch，但必须保留语义化 HTML、正确 HTTP 状态、无 JavaScript 回退和 reduced-motion 支持。

项目在可见规划期内固定采用 Django 服务端模板 + htmx，不建设通用 JSON Data API，不引入 DRF/OpenAPI/Swagger，也不为 SPA、独立前端或假设中的移动客户端预留第二套接口。浏览器交互以完整 HTML 页面、HTML fragment、Django Form、Session、CSRF、Policy 与 Service 为唯一契约；外部地图、音乐和审计服务的供应商 API 不属于这一限制。

页面必需的优化后 WebP/SVG 等静态资产随代码版本化并通过 `collectstatic` 部署；源 PNG/PSD、AI 中间稿和用户上传媒体不进入 Git，也不把必需资产留给上线时人工补传。

## 文档入口

- [V2 开发指南](V2GUIDE.md)：当前版本、全局架构与路线决策
- [项目开发说明](DEVELOPMENT.md)：项目结构、路由与本地开发入口
- [文档中心](docs/README.md)：编码、版本升级、异步、日志与 Git 专项指南
- [Devenir 主题规范](themes/devenir/DEVELOPMENT.md)：设计语言、模板、静态资源与响应式验收
