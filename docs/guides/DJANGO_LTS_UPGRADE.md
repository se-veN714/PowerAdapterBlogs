# Django 5.2 LTS 升级记录

> **文档权重**：86（框架版本、兼容边界与升级验证）
> **最后更新**：2026-07-21

## 结论

- 运行版本固定为 `Django==5.2.16`，这是 5.2 LTS 当前最新补丁版。
- 5.2 LTS 扩展安全支持至 2028 年 4 月；已停止支持的 5.1 仅保留临时开发兼容路径，不再作为部署目标。
- 完整测试集在 Django 5.2.16 和旧环境 Django 5.1.5 上分别运行 87 项，均通过；两边 system check 均为 0 issues。
- 本次没有数据库字段变化，不产生迁移。

## 已采用的 5.2 能力

1. `django.urls.reverse(query=...)`：Post Stream 的分类、搜索和分页 URL 由 Python 统一生成，模板不再手工拼接 query string。搜索关键词会按标准规则编码，普通链接与 htmx `hx-get` 使用同一个 canonical URL。
2. `HttpResponse.text` 已确认可用于 5.2 测试与调试；正式回归断言继续使用跨版本 API，以维持 5.1 过渡验证。
3. `manage.py shell` 自动导入已安装 App 的模型，可直接用于个人博客的数据探索；无需项目代码适配。
4. Django 5.2 默认 PBKDF2 迭代次数提高到 1,000,000，现有 Django 密码体系自动获得更强的新密码哈希参数，旧密码会沿用 Django 的渐进升级机制。

## 暂未采用

- `CompositePrimaryKey`：现有模型和外键已经稳定，迁移收益不足，贸然使用会扩大 Admin、DRF、权限和历史数据风险。
- 异步认证接口：当前应用仍是同步 CBV/WSGI 风格；异步演进作为本地试验计划维护，不属于本次 LTS 升级交付。
- 自定义 `BoundField`：现有 Devenir 表单主要由 widget 和 CSS 控制，暂时没有重复逻辑需要抽象。

## 兼容与部署边界

- `Blogs.views.PostListView.get_page_url()` 在 5.2 使用 `reverse(query=...)`；旧 5.1 环境暂时回退到 `urllib.parse.urlencode()`，用于尚未重建虚拟环境的开发机。
- 部署时必须重新安装 `requirements.txt`，并在升级后清理 Django 页面缓存，避免跨版本缓存对象残留。
- PostgreSQL 生产环境须为 14 或更高版本；Django 5.2 不再支持 PostgreSQL 13。
- 项目 `.venv` 的启动器仍指向已删除的旧 Python 安装。它不影响依赖锁定或本次验证，但应重新创建虚拟环境，不能继续把该启动器用于部署。

## 验证命令

```powershell
python -Wa manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
ruff check .
```

## 参考

- [Django 官方下载与支持版本](https://www.djangoproject.com/download/)
- [Django 5.2 release notes](https://docs.djangoproject.com/en/5.2/releases/5.2/)
- [官方升级指南](https://docs.djangoproject.com/en/5.2/howto/upgrade-version/)
