# PAdif MCP 差异预算与回复分页验证

日期：2026-11-11。范围：MCP 差异计算预算、差异操作分页、批注回复分页和长字段引用。仅本地实现/验证；没有生产操作、提交、推送或部署，无模型/迁移变更。

## 1. 改动与边界

- `compare_versions` 复用既有句子 diff、源码行提示和统计算法，在不初始化 Django/数据库的独立 Python 子进程计算。抽出的纯序列化函数由旧 API 共用，旧 API 小结果与 MCP 结果对照一致。一次比较只计算一遍 diff，再从相同 ops 计算统计。
- 默认 3 秒墙钟预算，预检耗时从子进程预算扣除；`subprocess.run` 超时会 kill 并等待回收。每侧上限 2 MiB、10,000 句；句数乘积与最长句字符数乘积各最多 4,000,000。每个 Web 进程最多两个同时计算的子进程，超容量立即 `DIFF_BUSY`，不无限排队。
- 超时/复杂度超限返回 `DIFF_TOO_COMPLEX`，不返回半份成功；启动失败返回安全常量错误。预算不是严格的整个 HTTP 三秒 SLA：数据库查询、操作系统创建/回收与序列化仍有额外开销。并发限制不是集群总配额，数据规模预检不是 OS 内存硬限制。
- 可选 offset/limit 固定比较两个 version ID，返回 `diff.ops`、全局统计、`total_ops`、`next_offset` 和列表完整性标记；页长可按实际 64 KiB wire 预算缩小。长操作明确省略 text/inner，提供版本类型引用；replace 有 before/after。引用指向完整版本，既有行号仅作定位提示，不伪造精确字符偏移。
- `list_annotations(paginate_replies=true)` 返回有界回复预览和签名 `next_reply_cursor`。续取使用 version_id/reply_annotation_id/reply_cursor；游标绑定连接、批注、版本、最后 ID 和快照最大 ID，1 小时过期。后来追加回复不混入同一轮遍历；完整新线程需重开第一页。原作者与时间保持不变。
- 批注、回复、处理说明的长正文给显式 incomplete 标记与 `read_content_chunk` 可读引用；长 selected_text 引用原版本行范围。实际 wire 预算会缩短列表/回复页，或将预览减为一条引用，不跳过未显示项。
- 原有小请求保持结果形状；旧超大差异/线程显式报错并给分页指引。旧线程超过 100 回复亦需选择新分页合同。每页仍走现有账号、板块、逐篇 AI+ 和 scope 检查。主线仍仅网页确认。
- 本轮不为网页/旧 API 差异、提交版本时的统计增加统一计算预算，不增加上传、授权能力或新的业务工具。总工具数仍为 13，MCP serverInfo 版本 1.2.0。

## 2. 本地回归

新增 `agent_mcp/tests/test_bounded_diff_threads.py`，覆盖：

| 矩阵关联 | 实际验证 |
|---|---|
| G16/E04 | 实际 2 MiB/句数/字符复杂度预检；拒绝时不启动进程；3 秒配置传入 timeout，超时错误不带 partial diff |
| G16 | 真实子进程用 20 ms 测试截止时间触发超时，确认子进程已回收、容量释放后下次比较成功。此项测试中缩短截止时间，不伪称跑满生产三秒 |
| G12/G13 | 忙时不启动进程，启动错误不回显路径；固定输入复杂度超限不建议反复重试或越过 MCP |
| E04/L09 | 旧 API 对照一致、全局统计跨页一致；HTTP 实际响应含 text/structuredContent 的双份大小 ≤64 KiB，完整遍历无缺失；长单项显式 source_ref |
| E05/G03 | 线程原作者/时间、所有回复顺序续取；追加回复不混快照；批注必须属于所给版本 |
| E05/L04/L09 | 超长回复/处理说明给类型引用，回复正文经 chunk 完整还原；含反斜线/引号/控制字符的 HTTP 列表与线程页均有界且不漏项 |
| G01/G07 | 跨连接、篡改、过期和错批注游标拒绝；scope 降权与逐篇 AI+ 撤销后拒绝续页 |
| G15/R02 | 原有小线程结果保留，旧大结果提供恢复指引；旧业务/权限/主线回归继续运行 |

命令（隔离本地 PostgreSQL 测试库，非生产）：

```powershell
$env:PYTHONPATH="$PWD\.local;$PWD"
.venv\Scripts\python.exe manage.py test agent_mcp padif accounts.tests.test_agent_auth --settings=padif_mcp_test_runtime --keepdb --noinput
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=padif_mcp_test_runtime
.venv\Scripts\python.exe -m ruff check agent_mcp padif/core/diff_payload.py padif/core/differ.py padif/api.py --select F,E9
git diff --check
```

执行结果：新增专项 15 项通过；完整 MCP/PAdif/旧 Agent API 回归共 186 项通过（53.334 秒）。迁移检查无变化，Ruff F/E9、`git diff --check` 和 30 个本地 Markdown 链接检查通过。执行日志在忽略目录 `.local/mcp-budget-focused.log`、`.local/mcp-budget-regression.log`。

## 3. 官方 SDK 与浏览器

使用新建的一次性本地账号/文档、8777 服务、隔离 Chromium 和官方 Python MCP SDK，实际完成 DCR/PKCE、显式 OAuth 同意、全部 13 工具发现、差异分页完整遍历/全局统计对照、回复预览与续页、分支提交/patch、幂等、令牌刷新和网页撤销；main 头不变。新凭证只用于本地测试，不读取 WorkBuddy 缓存。

证据：`.local/tool-budget-sdk-browser.log`、`.local/browser-qa/mcp-g6O2qY/report.json`。1198×715 与 390×844 横向溢出均为 0。报告将已知 MathJax 重复启动基线错误单列；不将该公共模板旧问题视为此次新增错误。未做新的原生 WorkBuddy 实测，也未声明客户端文件/终端沙箱安全。

## 4. 后续

本轮仍不包含暂存上传/文件适配器、恶意 HTML/外部资源的完整浏览器验收或全矩阵竞态穷举。下一阶段可按已确认 Spec 实现私有 Markdown 暂存上传及验证；需用户继续授权，不自动开始。
