# PAdif MCP 私有 Markdown 暂存验证

日期：2026-11-11。范围：六个暂存工具、私有 PostgreSQL 分块存储、登录文件选择页、校验/原子提交及清理。仅本地实现与验证；没有生产访问、源码提交、推送、部署或生产 timer 启用。

## 1. 实现和安全边界

工具总数 19。`begin/append/status/validate/commit/cancel_markdown_upload` 复用原连接、账号、资格、人类文章角色、AI+ version 操作和 OAuth scope。status 标为只读，不要求 request_id；其他操作使用原幂等回执。校验失败和取消会清除暂存字节，工具 destructiveHint 如实标记。

状态路径、配额、固定块、manifest 一次绑定、绝对 30 分钟期限及两种 SHA-256 见 [Spec](TOOL_SAFETY_SPEC.md) 和 [README](README.md)。数据库原字节不进入公开 media，不根据文件名拼接路径。文件扩展名/MIME 不等于可信证明：服务端组合检查文件名、实际块长度/整体长度、SHA-256、合法 UTF-8、非空文本、NUL/C0/DEL 和已知二进制头。HTML/脚本代码文本不按关键词删除，上传页不渲染正文或抓取文中 URL。

任务固定连接、文章、分支、base 和权限版本；正常 token 刷新继续原任务，新授权不继承。当前权限撤销立即拒绝，重新开通不能恢复旧权限周期任务。提交经已有版本服务，仅原独立分支生成一次版本；main 仍网页确认。失败、审计异常、存储异常回滚，不能先回成功再后台写版本。

`compare_versions(to_upload_id=...)` 和 `read_content_chunk(upload_markdown, UUID)` 支持校验稿检查，额外检查原连接 version scope、本文写作操作和任务状态。未公开新增通用文件/目录/下载功能。commit 后正文可定位到任务已提交的不可变版本，暂存块立即清除。

单例 DB 行锁串行准入，用户最多 3 个未完成任务/8 MiB 预留原字节；未选文件先预留 2 MiB。部署级默认 1024 活动任务/128 MiB 预留。配额不是整个 PostgreSQL RSS/磁盘/WAL/备份大小；清除活跃表行不代表安全擦除旧页或备份。共享缓存计数用于每连接每分钟 10 次创建/60 次分块，生产需使用现有共享缓存。

## 2. 回归与矩阵映射

专项测试：`test_uploads.py`、`test_upload_concurrency.py`、`test_upload_migration.py`。

| 矩阵 | 实际证据 |
|---|---|
| U01/U20/C01/C02 | awaiting_file 预留、用户登录文件页、CSRF 拒绝、其他用户 404、manifest 原子冻结；浏览器在 manifest 成功前不发送字节 |
| U02/U03/U11 | 乱序块、同块幂等、冲突块、缺块、错误序号/长度、校验后禁止追加；没有逐块版本 |
| U04/U06/U14/G01 | 新连接不得访问旧任务，六工具逐项 scope/AI+ 拒绝；权限版本重新开通导致旧任务失效。非全条件笛卡尔积穷举 |
| U05 | 官方 SDK 在 awaiting_file 时实际刷新 OAuth，旧任务继续网站上传并提交 |
| U07/U08/U09/U10 | 非法 UTF-8/NUL/二进制头/空文本/错误整体哈希导致 invalidated 并清块；名称路径/控制/后缀/长度拒绝；BOM/CRLF/中文/emoji/空行/尾 LF 哈希与内容保真 |
| U12/U13/G04/G11 | PostgreSQL 真并发不同 request_id 仅提交一个版本；归档/base 检查；main 拒绝；审计失败时任务/块/版本/回执回滚 |
| U15/U16 | 重复取消安全、不能取消已提交版本；过期即时拒绝且命令可清理，状态/哈希历史保留 |
| U17 | 不同连接、不同文章并发准入仍只有三个槽位；全局准入限制拒绝；实际缓存分块计数第 61 次拒绝 |
| U18 | 模拟块存储异常后无块/成功回执/错误状态残留，正常重试可完成；未做真实 PostgreSQL 磁盘耗尽/进程强杀实验 |
| U19/C06/C07 | 暂存只有登录页面和授权工具，无公开字节 URL；七稿包含代码围栏 script 与内网图片文本，上传页未执行。此证据不替代所有旧预览/全屏/diff/批注渲染的恶意内容验收 |
| C09/R02 | 新一次性账号＋官方 SDK＋隔离 Chromium 处理七份约 9k–16k 字符稿件，分别提交独立分支、逐篇原始/规范 SHA 核对、main 不变，随后刷新与网页撤销通过 |
| R01/R03 | 0005→0006 迁移前后历史模型行指纹一致；本地预览库实际迁移前后文章/版本/批注/成员/授权/连接/回执指纹一致；状态及失败原因使用安全审计元数据，不记录原字节或凭证 |

命令（隔离本地 PostgreSQL，不是生产）：

```powershell
$env:PYTHONPATH="$PWD\.local;$PWD"
.venv\Scripts\python.exe manage.py test agent_mcp padif accounts.tests.test_agent_auth --settings=padif_mcp_test_runtime --keepdb --noinput
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=padif_mcp_test_runtime
.venv\Scripts\python.exe -m ruff check agent_mcp --select F,E9
git diff --check
```

新增专项共 16 项，最终串行完整回归 202 项通过（93.931 秒），包含新增请求入口长度测试。Ruff F/E9、JS 语法、`git diff --check`、36 个 Markdown 链接及迁移一致性检查通过。日志：`.local/mcp-upload-final-focused.log`、`.local/mcp-upload-final-regression.log`。一次误并行的共享测试库运行因迁移锁竞争作废，最终结果以串行日志为准。实际预览库仅应用新增迁移 0006，输出 `PRESERVATION_MATCH` 后才新建本轮一次性测试账号和稿件，不修改原有用户数据。

## 3. 浏览器/SDK 证据

运行现有 `browser_oauth.cjs`，设置 `PADIF_MCP_QA_UPLOAD=1`、本地 8778 与新一次性账号。浏览器通过真实 file input 选择文件并正常 CSRF 上传；文件字节不作为 MCP 模型工具参数往返，SDK 只收任务/哈希/摘要，再调用校验、检查与提交。正文回读仅用于测试程序计算哈希，不提供客户端凭证或上传 token。

最终记录：`.local/upload-sdk-browser-final.log`、`.local/browser-qa/mcp-nJOApq/report.json`。七份稿件约 26–47 KiB 原始字节；1198×715、390×844 无横向溢出。截图 `upload-1198.png`、`upload-390.png`；移动图已人工检查。新增页面错误为空；已有公共 MathJax 重复启动问题单列为 baseline，不在本轮修复。

这不是新的原生 WorkBuddy 文件适配器验收。WorkBuddy 自动路径未支持；不得因其缺少受控文件能力去查找或解密缓存 OAuth 凭证。默认网站选文件路径已实际验证。

## 4. 清理和待发布边界

扩展 `cleanup_padif_mcp` 扫描已过期/撤销/资格或文章权限失效任务，删除块并保留审计。新增独立 `deploy/systemd/poweradapter-mcp-cleanup.service/.timer`，每五分钟执行，保留既有按小时的设备授权清理。Windows 本地验证命令和状态变化，未在 Linux 激活/运行 timer；未来批准发布时须安装启用、检查 calendar/最近执行日志和过期任务清理。

迁移加表、外键与约束，无数据重写脚本。未做生产验证，不宣称整张验收矩阵全部通过；真实文件适配器隔离、所有旧渲染面恶意内容、全竞态排列、真实磁盘故障及 Linux timer 实测仍分列待验证。

本阶段完成后建议用户先验收本地文件选择与提交体验，再决定源码提交及正式发布，不自动部署。
