# PowerAdapterBlogs

> **文档权重**：50（项目介绍；实现与路线以高权重文档为准）

- 这个项目是我的个人博客项目，同时帮助我学习 Django 框架

项目在可见规划期内固定采用 Django 服务端模板 + htmx，不建设通用 JSON Data API，不引入 DRF/OpenAPI/Swagger，也不为 SPA、独立前端或假设中的移动客户端预留第二套接口。浏览器交互以完整 HTML 页面、HTML fragment、Django Form、Session、CSRF、Policy 与 Service 为唯一契约；外部地图、音乐和审计服务的供应商 API 不属于这一限制。

## 文档入口

- [V2 开发指南](V2GUIDE.md)：当前版本、全局架构与路线决策
- [项目开发说明](DEVELOPMENT.md)：项目结构、路由与本地开发入口
- [文档中心](docs/README.md)：编码、版本升级、异步、日志与 Git 专项指南
