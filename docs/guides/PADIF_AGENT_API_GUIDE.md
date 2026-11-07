# PAdif Agent API

PAdif 为登录用户的 Agent 提供设备码授权和 Bearer API。Agent 不需要保存用户密码，也不应复用浏览器会话。

## 1. 发现能力

先请求 `GET /padif/api/capabilities/`。该接口不需要令牌，返回当前站点的授权入口、scope、资源 URL 模板和稳定错误码。生产环境应使用 HTTPS。

## 2. 设备授权

1. Agent `POST /accounts/agent/device/start/`：

```json
{"client_name":"Writing Agent","scopes":["padif:read","padif:annotate","padif:version"]}
```

2. 将返回的 `verification_uri_complete` 展示给用户。用户在已登录浏览器中确认授权；PAdif 权限不足的用户无法批准带 `padif:*` scope 的请求。
3. Agent 使用 `device_code` 轮询 `POST /accounts/agent/device/token/`：

```json
{"device_code":"..."}
```

收到 `authorization_pending` 时按响应中的 `interval` 秒等待后重试。成功响应中的 `access_token` 只在返回时可见，之后用 `Authorization: Bearer <access_token>` 调用 API。默认设备码有效期 10 分钟，访问令牌有效期 15 分钟。

## 3. PAdif 资源

- `GET /padif/api/documents/`：列出当前账号可访问的文档和当前版本。
- `GET /padif/api/documents/{document_id}/workspace/`：读取文档、全部版本、当前版本正文和当前版本批注。
- `GET /padif/api/documents/{document_id}/diff/?from_version={id}&to_version={id}`：读取结构化句子级 diff、行号和统计。
- `POST /padif/api/documents/{document_id}/versions/`：追加版本。提交 `base_version_id` 可检测并发修改；过期时返回 `409 STALE_BASE_VERSION`。
- `POST /padif/api/versions/{version_id}/annotations/`：创建批注。
- `PATCH /padif/api/annotations/{annotation_id}/`：将批注标记为 `resolved` 或 `rejected`，必须提交非空 `resolution_note`。
- `POST /padif/api/annotations/{annotation_id}/replies/`：追加批注回复。

写操作分别需要 `padif:version` 或 `padif:annotate`；读取操作需要 `padif:read`。所有接口仍要求授权账号具有 PAdif 使用权限。

## 4. 错误处理

Agent 应按 `error` 字段分支处理：

- `AUTH_REQUIRED` / `INVALID_TOKEN`：重新走设备授权。
- `INSUFFICIENT_SCOPE`：不能通过重试解决，需要用户重新授予更高 scope。
- `STALE_BASE_VERSION`：重新读取 workspace，基于最新版本生成新提交。
- `INVALID_JSON`、`INVALID_*`：修正请求后再提交。
- `DOCUMENT_NOT_FOUND`、`VERSION_NOT_FOUND`、`ANNOTATION_NOT_FOUND`：停止对该资源的后续写入。

令牌撤销入口为 `POST /accounts/agent/tokens/{token_id}/revoke/`，仅令牌所属用户可调用。

账号持有人也可以在登录后打开 `/accounts/security/agents/` 查看自己签发过的令牌。页面只显示客户端名称、scope、指纹、时间和状态，不显示令牌正文；有效令牌可以直接撤销。

设备授权创建入口按客户端 IP 限流，默认每小时最多 10 次，超限返回 HTTP 429 和 `Retry-After`。生产环境应定期执行：

```bash
docker compose exec -T web python manage.py cleanup_agent_authorizations
```

清理任务会删除过期/撤销令牌和已过期且不再关联有效令牌的设备授权；仍有有效访问令牌的授权记录会保留。

生产部署已启用 `poweradapter-agent-cleanup.timer`，按小时触发同一个命令；也可以用以下命令检查最近一次执行：

```bash
systemctl status poweradapter-agent-cleanup.timer
journalctl -u poweradapter-agent-cleanup.service -n 20 --no-pager
```

## 5. 分支稿工作流

分支复用既有权限：读取需要 `padif:read`，创建、提交及发布需要 `padif:version`；批注仍需要 `padif:annotate`。浏览器登录态不能代替 Bearer 授权。

1. 从 workspace 选择同文档版本，调用 `POST /padif/api/documents/{document_id}/branches/`：
   `{"name":"rewrite-v2","fork_from_version_id":123,"description":"改稿实验"}`。
2. `GET /padif/api/documents/{document_id}/workspace/?branch=rewrite-v2` 读取所选分支的正文和批注。空分支的有效头是分叉源，不生成哨兵版本；`selected_branch` 表示所选分支，`current_version.branch_name` 表示版本真正所属分支。`versions` 仍包含整个文档的历史，版本项增加 `branch_id/branch_name/parent_version_id`。
3. 对原 versions 端点提交 `branch` 与有效头 `base_version_id`：
   `{"branch":"rewrite-v2","base_version_id":123,"content":"修订正文","commit_message":"改写开场","version_kind":"minor"}`。
   分支首提交从源版本号递增；只推进该分支，不改变主线。省略 branch 仍写主线；旧客户端可省略 base，但将失去过期基准保护，新客户端应总是携带它。
4. 准备发布时，分别读取主线与源分支 workspace，记录两端头 id；调用现有 diff 端点审阅主线→分支整稿差异，并取得用户对整稿替换的明确确认。**这不是自动合并**，主线后来增加的文字不会自动保留在分支正文里。
5. 仅在确认后调用 `POST /padif/api/documents/{document_id}/branches/{branch_id}/publish/`：
   `{"commit_message":"采用修订稿","version_kind":"minor","base_version_id":124,"source_version_id":125,"confirm_replace":true}`。
   服务在锁内校验两头，在主线追加快照，保留源分支和所有历史、批注。新主线版本不复制源批注。

`STALE_BASE_VERSION`、`STALE_SOURCE_VERSION` 返回 409：重读两端、重新比较并重新取得确认，不能仅替换版本 id 后自动重试。首次发布成功后，同一请求重试因 base 过期而返回 409，不会重复写入。`BRANCH_ARCHIVED` 返回 409；`EMPTY_BRANCH`、`CONFIRMATION_REQUIRED` 返回 400；未知/跨文档资源返回 404。JSON 的 version id 只能是正整数，不能是字符串或布尔值。

`branches` 列表包含 id、name、is_default、forked_from_version_id、head_version_id、head_semantic_version、archived_at。归档分支仍可读可比较，但不能提交或发布；MVP 的归档入口仅在浏览器提供，归档不删除任何历史或批注。分支名只允许小写 ASCII 字母、数字和连字符，最长 64 字符，不能复用 main 或归档分支名称。发现接口返回创建/发布 URL 模板与所需确认字段。
