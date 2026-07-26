# PowerAdapterBlogs 上线检查清单

> **文档权重**：84（生产部署与发布验收执行清单）
> **适用版本**：v2.4+
> **更新**：2026-07-27
> **上位依据**：`V2GUIDE.md`、`BLOG_FOUNDATION_GUIDE.md`、`accounts/SECURITY_ROADMAP.md`

本清单用于每次正式部署前后的人工确认，不替代备份、监控或回滚方案。涉及证书、数据库和 Redis 的命令必须先确认目标环境。

## 1. 发布前

- [ ] 工作区提交已审核，迁移文件与代码属于同一版本。
- [ ] `python manage.py test` 全量通过。
- [ ] `ruff check` 与 `python manage.py check --deploy --settings=PowerAdapterBlogs.settings.product` 通过。
- [ ] 数据库与 MongoDB 审计数据完成可恢复备份，并记录恢复入口。
- [ ] 确认 `DJANGO_SECRET_KEY`、数据库、Redis、MongoDB、邮件和 HMAC 密钥来自生产环境变量，而非开发默认值。
- [ ] `PUBLIC_SITE_URL` 为最终 HTTPS Origin，不包含后台域名或尾部路径。
- [ ] `SECURITY_CONTACT_EMAIL` 可正常收件，且允许接收外部联系人的安全报告。
- [ ] `DJANGO_ALLOWED_HOSTS` 与 `DJANGO_CSRF_TRUSTED_ORIGINS` 只包含实际域名。

## 2. 部署步骤

- [ ] 进入正确虚拟环境并安装锁定版本依赖。
- [ ] 执行 `python manage.py migrate --plan`，人工确认后再执行 `python manage.py migrate`。
- [ ] 执行 `python manage.py collectstatic --noinput`。
- [ ] 平滑重启 Gunicorn/Waitress 服务，确认旧 worker 已退出。
- [ ] 执行 `nginx -t` 后再 reload；不得在配置校验失败时重载。

## 3. 公网冒烟检查

- [ ] 首页、文章列表、文章详情、归档、About 与隐私页返回 200。
- [ ] `/feed/`、`/feed/atom/` 和 `/sitemap.xml/` 只包含公开已发布文章。
- [ ] `/robots.txt` 指向正确的 HTTPS Sitemap。
- [ ] `/.well-known/security.txt` 包含可用 Contact、未来 Expires、`zh/en/ja` 语言偏好与当前域名 Canonical。
- [ ] 页面 canonical、Open Graph URL 与图片 URL 使用生产 HTTPS 域名。
- [ ] 随机不存在路径返回 Devenir 404 且不包含 Debug/Traceback。
- [ ] 邀请邮件和修改密码验证码邮件中的链接、发件人和有效期正确。
- [ ] 普通访客无法访问 Dashboard、系统后台、内部文章、草稿和修订端点。

## 4. 安全与运行状态

- [ ] `DEBUG=False`，Cookie Secure/HttpOnly/SameSite 与 HSTS 配置符合预期。
- [ ] Redis DB 1（缓存/限流）与 DB 2（Session）没有误用同一清理操作。
- [ ] Nginx 只转发受信代理头；应用服务不直接暴露公网监听地址。
- [ ] PostgreSQL 日志完整性检查通过；MongoDB HMAC 审计链无异常断点。
- [ ] 日志中没有验证码、密码、Token、完整 Session ID 或不必要的个人信息。

## 5. 回滚准备

- [ ] 记录本次提交、迁移头、静态文件版本和部署时间。
- [ ] 明确代码回滚与数据库迁移回滚是否兼容；不可逆迁移必须提前准备恢复脚本或备份恢复。
- [ ] 发布后观察错误率、登录失败、邮件发送、数据库连接和 Redis 连接。
- [ ] 发现权限泄漏、认证绕过或数据破坏时，优先隔离入口并保留审计证据，再执行回滚。

## 6. `security.txt` 维护

- [ ] 至少每 6 个月人工确认安全联系邮箱仍然有效。
- [ ] 若安全联系地址或生产域名变化，同次发布更新环境变量并执行公网检查。
- [ ] 没有真实 Policy、Encryption、Acknowledgments 或 Hiring 页面时，不发布对应字段。
- [ ] 后续若引入漏洞报告政策页面，再增加 `Policy:`；若提供报告加密公钥，再增加 `Encryption:`。
