# PAdif 分支与世界线回归

## Django / PostgreSQL

```powershell
.\.venv\Scripts\python.exe manage.py test padif.tests accounts.tests.test_agent_auth
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

默认开发配置使用 SQLite，会跳过真实行锁测试。完整验收应给 test 命令传入你自己的隔离 PostgreSQL 配置 `--settings=<local_test_settings>`，测试账号须能创建测试数据库；不要使用生产数据库。迁移测试从 PAdif 0004 的历史模型构造数据，再验证 0005 回填和异常回滚。

## 前端交互

```powershell
node padif/tests/test_rail_interactions.cjs
```

这些脚本测试覆盖抽屉状态、焦点、导航滚动恢复和未保存对象保留，不替代真实浏览器验收。

## 隔离浏览器验收

安装 Playwright 和相应 Chromium 后，启动隔离的本地预览。准备具有 PAdif 使用权限的测试账号，以及包含 `opening`、`ending` 和第三条活跃分支的测试文档；文档应有主线历史和分支提交。测试只登录、编辑暂存内容和切换界面，不提交稿件或上传版本。

```powershell
$env:PADIF_QA_BASE_URL = 'http://127.0.0.1:8771'
$env:PADIF_QA_DOCUMENT_ID = '2'
$env:PADIF_QA_USERNAME = '<local-test-user>'
$env:PADIF_QA_PASSWORD = '<local-test-password>'
node padif/tests/browser_worldlines.cjs
```

脚本只接受 localhost / 127.0.0.1 目标。预览环境应关闭遮挡控件的 Django Debug Toolbar；这不需要改变认证或生产设置。

验收视口为 `1198×715`、`1920×1080`，覆盖抽屉开关、Escape、编辑区宽度、稿件与 File 对象保留、分支切换时的焦点/编辑器展开状态/滚动恢复、重新加载后的收起偏好，以及页面和抽屉横向溢出。报告与截图输出到 `.local/browser-qa/worldlines/`，不提交测试账号、数据库或运行产物。
