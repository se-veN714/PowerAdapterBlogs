# PAdif MCP 工具安全第一阶段验证

日期：2026-11-11。范围：统一工具入口、有界读取、精确局部修改。本地实现和验证；未提交、推送或部署。生产账号、文章、版本、批注与授权数据没有操作。

后续更新：本页保留第一阶段运行时证据；其中 diff/回复分页缺口已在[第二阶段](TOOL_SAFETY_PHASE2_VALIDATION.md)本地补齐，以该记录的当前合同和边界为准。

完整目标见 [Spec](TOOL_SAFETY_SPEC.md) 和 [验收矩阵](TOOL_SAFETY_ACCEPTANCE_MATRIX.md)。本记录不代表上传阶段或整张矩阵通过。

## 1. 本阶段实际合同

- 原有 10 个工具保留，新增 `get_document_outline`、`read_content_chunk`、`apply_version_patch`，合计 13 个。工作区增加可选 `include_content=false`，只返回有界元数据；省略仍请求旧全文。
- 所有调用重新读取连接、资格和当前 scope；写操作锁后复核，先检查逐篇权限，再读取幂等回执。原有角色、AI+、OAuth scope 和网页主线确认边界不变。
- 所有工具结果按包含 text/structuredContent 双份内容的实际 JSON-RPC 序列化限制到 64 KiB。超限显式失败，不静默截稿；写结果超限或审计失败，业务对象与成功回执一起回滚。
- 新工具的完整 JSON-RPC 请求不超过 64 KiB；旧传输仍为 2,300,000 字节。RPC 字符串 ID 最长 128 字符。非法 Unicode、实际 NUL 和未知字段拒绝，错误不回显稿件。
- 分块正文最多 16 KiB UTF-8，必要时按实际响应预算缩小。签名 cursor 有效一小时，绑定连接、来源、哈希与偏移；版本 ID 固定，处理说明变化需重读。来源只允许版本、批注、回复和处理说明，不接受路径/URL。
- patch 最多 20 项，替换正文总量 32 KiB、最终正文 2 MiB。采用 1 起始半开行范围和精确原文、base ID、规范哈希；冲突整次失败，空行和末尾换行保留。规范化为无 BOM 的 UTF-8/LF，不改写历史版本。
- 目录识别围栏代码外的 ATX/setext 标题，标题最多 200 字符，超过 10,000 个标题拒绝；不是完整 CommonMark 语义解析器。

## 2. 可复现测试与证据

设置：隔离本地 PostgreSQL 测试库 `test_padif_branching`，`padif_mcp_test_runtime`；数据库迁移测试属于测试库。浏览器验收使用独立 8776 服务和新建一次性账号/文档，不使用真实账号或客户端凭证。

| 矩阵关联 | 实际证据 | 本阶段结果和限制 |
|---|---|---|
| G01/G07/G14 | `test_tool_safety.ToolSafetyTests`，既有 `test_operation_web`/`test_access_review` | 原 10 工具的陈旧连接撤销、失效账号、过期、scope 清空均拒绝；降权后旧写回执不可重放。不是 G01 全部条件对全部未来工具的笛卡尔积证明 |
| G02/G03/G05 | `test_long_documents.test_other_document_sources_and_versions_never_leak_metadata`，既有协作/权限回归 | 新读入口猜测私有版本/批注 ID 和跨文章版本无正文/哈希泄漏；管理员未获逐篇授权不能绕过 |
| G04/G06/G13 | `test_long_documents` 的 main、参数、NUL/Unicode、范围和额外字段负例 | main 不可 patch；拒绝非法输入而不回显敏感样例。未做全系统日志安全审计 |
| G08/G10/G11/L08 | `test_patch_concurrency.ConcurrentPatchTests`，`test_tool_safety` | PostgreSQL 真并发：同请求只写一次，不同请求同 base 仅一方成功；等待连接锁期间降 scope 后拒绝；审计失败及超大写响应事务回滚。G09/G10 的全部撤销/归档获锁顺序仍未穷举 |
| E02/E03/L01/L02/L05/L06/L09 | `test_long_documents`，`test_tool_safety.BoundedTransportTests` | 摘要无正文、目录行号、中文/emoji/引号/反斜线/控制字符块还原、实际 wire 预算、插删空行/EOF、BOM/CRLF、精确原文/哈希/重叠拒绝 |
| L03/L04 | `test_chunk_cursor_keeps_original_version_after_branch_advances`，mutable-note 和跨连接 cursor 测试 | 原版本读取不随分支头改变，处理说明变化拒绝旧 cursor；来源白名单和逐篇权限共用入口。未覆盖所有来源组合及可控时钟过期排列 |
| R02/R04 | `tests/browser_oauth.cjs` + `tests/e2e_client.py` | 实际 Chromium OAuth 同意、官方 Python MCP SDK DCR/PKCE、13 工具、摘要/目录/块读取、分支提交/patch、幂等、批注/回复/处理、刷新、网页撤销通过，main 不变 |
| R01/R05 | `makemigrations --check --dry-run`；变更文件检查 | 无模型变更、无新迁移；未连接生产，无发布操作 |

执行结果：MCP/PAdif 159 项测试通过（51.245 秒），MFA 53 项通过（1.832 秒）；`makemigrations --check --dry-run` 无变化，Ruff F/E9 与 `git diff --check` 通过。本阶段新增 21 项测试包含真实 PostgreSQL 并发和 wire 字节校验。

执行命令（在项目根目录，先设置本地 PYTHONPATH）：

```powershell
$env:PYTHONPATH="$PWD\.local;$PWD"
.venv\Scripts\python.exe manage.py test agent_mcp padif --settings=padif_mcp_test_runtime --keepdb --noinput
.venv\Scripts\python.exe manage.py test accounts.tests.test_mfa_services accounts.tests.test_mfa_h2 accounts.tests.test_mfa_device_model accounts.tests.test_mfa_crypto --settings=padif_mcp_test_runtime --keepdb --noinput
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=padif_mcp_test_runtime
.venv\Scripts\python.exe -m ruff check agent_mcp --select F,E9
```

运行结果保留于忽略目录：`.local/mcp-safety-final-regression.log`、`.local/tool-safety-mfa-regression.log`、`.local/tool-safety-sdk-browser.log`。浏览器/SDK 报告在 `.local/browser-qa/mcp-Cs2HRB/report.json`：1198×715 和 390×844 横向溢出均为 0；新增页面错误为空。报告另列已有 MathJax 重复启动错误，本轮没有修改该公共模板问题。截图只辅助此次现有 OAuth 流程，不声称完成新的 UI 或恶意渲染验收。

本次是官方 SDK 和隔离 Chromium 证据，**不是新的原生 WorkBuddy 验收**，也不能证明客户端终端/凭证文件被沙箱隔离。

## 3. 明确保留的后续关卡

- U01–U20 等暂存上传、私有存储、网站选文件、清理配额与文件格式验证，以及 C01–C10 的文件适配器、七篇长稿整批验收：未实施/未执行，不暴露上传工具。
- G16/E04：diff 的独立进程、3 秒 CPU/资源隔离、分页与超长单项引用尚未接入。输出预算不等于计算预算；现有 SequenceMatcher 仍可能耗时。
- E05：现有完整批注线程超预算会失败；尚无全部线程分页入口。通用来源分块只能续取已知 ID 的正文，不代替线程枚举。
- C05–C08：恶意 HTML/SVG、外部图片、提示注入下真实客户端行为仍需独立浏览器/客户端验收。工具说明与 `content_is_untrusted` 不代表客户端强制隔离。
- 尚未声称 G09/G10 全排列竞态、全部超限边界和所有注入/日志用例通过。完整矩阵继续作为后续交付门槛。

建议下一阶段先补齐 diff/线程的有界遍历与计算预算，再开展暂存上传；每阶段继续保留主线网页确认与既有数据。
