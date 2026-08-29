# PowerAdapterBlogs 上线检查清单

> **文档权重**：84（生产部署与发布验收执行清单）
> **适用版本**：v2.5+
> **更新**：2026-08-28
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
- [ ] 无 IPv6 出口的主机设置有界 `EMAIL_TIMEOUT`，并验证至少两个 `EMAIL_SMTP_IPV4_FALLBACKS` 节点可达；TLS 仍以 `EMAIL_HOST` 校验证书，禁止使用不校验证书的 IP 直连。
- [ ] `DJANGO_ALLOWED_HOSTS` 与 `DJANGO_CSRF_TRUSTED_ORIGINS` 只包含实际域名。

## 2. Docker 部署步骤

- [ ] Linux 服务器安装 Docker Engine + Compose plugin；Windows 开发机继续使用 `run.py`，不要求 Docker Desktop/WSL。
- [ ] 从 `deploy/.env.production.example` 生成权限为 `0600` 的真实环境文件，三个 HMAC key、数据库密码、Mongo member key 与 mTLS proxy secret 彼此独立。
- [ ] 首次发布先启动 stateful services 并恢复经验证的现有 PostgreSQL 备份；确认 users、Categories、Boards、Memberships 与内容元数据存在。生产禁止运行依赖本地 Category ID 的 `seed_boards`。
- [ ] `docker compose --env-file deploy/.env.production -f compose.production.yml config` 通过。
- [ ] 执行一次性 `prepare` 服务；migration、collectstatic、Mongo audit index/transaction 检查与 Music JSON 幂等导入必须全部成功。
- [ ] 启动 `web`、`audit-worker`、`skate-worker`；确认 `/healthz/` 容器探针健康。该端点不经公网 Nginx 暴露。
- [ ] Host Nginx 只代理到 `127.0.0.1:18000`，静态与公开媒体使用 bind mount；`media-private` 永不配置 alias。
- [ ] 两个 vhost 均先 include SK8 media snippet；确认 `/media/skate/tmp/` 返回 404，不能被通用 `/media/` alias 抢先公开。
- [ ] Mongo root 只进入数据库初始化与 replica-set bootstrap；prepare 使用 index-only deploy 角色，audit worker 使用 delivery 角色，web/其他 worker 使用 verifier 角色。
- [ ] 2 GiB 首发保持 Gunicorn 1 worker 与 WiredTiger 0.256 GiB cache，观察后再扩容。
- [ ] 执行 `nginx -t` 后再 reload；不得在配置校验失败时重载。

## 3. 公网冒烟检查

- [ ] 首页、文章列表、文章详情、归档、About 与隐私页返回 200。
- [ ] `/feed/`、`/feed/atom/` 和 `/sitemap.xml/` 只包含公开已发布文章。
- [ ] `/robots.txt` 指向正确的 HTTPS Sitemap。
- [ ] `/.well-known/security.txt` 包含可用 Contact、未来 Expires、`zh/en/ja` 语言偏好与当前域名 Canonical。
- [ ] 页面 canonical、Open Graph URL 与图片 URL 使用生产 HTTPS 域名。
- [ ] 随机不存在路径返回 Devenir 404 且不包含 Debug/Traceback。
- [ ] 邀请邮件和修改密码验证码邮件中的链接、发件人和有效期正确；模拟首个 SMTP IPv4 节点不可达时，备用节点仍能完成投递。
- [ ] 普通访客无法访问 Dashboard、系统后台、内部文章、草稿和修订端点。

## 4. 安全与运行状态

- [ ] `DEBUG=False`，Cookie Secure/HttpOnly/SameSite 与 HSTS 配置符合预期。
- [ ] Redis DB 1（缓存/限流）与 DB 2（Session）没有误用同一清理操作。
- [ ] Nginx 只转发受信代理头；应用服务不直接暴露公网监听地址。
- [ ] 公网 vhost 对 `/super_admin/` 返回 404；独立管理 vhost 使用客户端 CA + CRL，并覆盖所有外部 `X-PA-*` 头。
- [ ] MongoDB 以 replica set 运行，`check_mongo_audit_deployment` 验证事务可用；不得降级到 standalone。
- [ ] 宿主 Nginx 使用项目批准的 OpenSSL 4.0 最新补丁，并记录版本/EOL 跟踪责任。
- [ ] PostgreSQL 日志完整性检查通过；MongoDB HMAC 审计链无异常断点。
- [ ] 日志中没有验证码、密码、Token、完整 Session ID 或不必要的个人信息。

## 5. 回滚准备

- [ ] 记录本次提交、迁移头、静态文件版本和部署时间。
- [ ] PostgreSQL、MongoDB、公开媒体、SK8 私有原片分别具备恢复验证；named volume 快照不能替代文件级恢复演练。
- [ ] 明确代码回滚与数据库迁移回滚是否兼容；不可逆迁移必须提前准备恢复脚本或备份恢复。
- [ ] 发布后观察错误率、登录失败、邮件发送、数据库连接和 Redis 连接。
- [ ] 发现权限泄漏、认证绕过或数据破坏时，优先隔离入口并保留审计证据，再执行回滚。

## 6. `security.txt` 维护

- [ ] 至少每 6 个月人工确认安全联系邮箱仍然有效。
- [ ] 若安全联系地址或生产域名变化，同次发布更新环境变量并执行公网检查。
- [ ] 没有真实 Policy、Encryption、Acknowledgments 或 Hiring 页面时，不发布对应字段。
- [ ] 后续若引入漏洞报告政策页面，再增加 `Policy:`；若提供报告加密公钥，再增加 `Encryption:`。
