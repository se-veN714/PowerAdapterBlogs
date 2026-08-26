# Security Audit Integrity Contract

> **文档权重**：95（安全审计数据与密码学契约）
>
> **最后更新**：2026-08-26

## Schema v1

Mongo 新事件包含 `_id == event_id`、`schema_version`、`event_type`、UTC canonical
`occurred_at/ingested_at`、仅含稳定 ID 的 `actor/target`、最小化 `context/change/outcome`，
以及 `integrity.algorithm/key_id/partition/sequence/previous_mac/mac`。

HMAC-SM3 覆盖除 `integrity.mac` 外的完整 envelope。Canonical JSON 使用 UTF-8、排序 key、
紧凑分隔符、六位微秒 UTC `Z`；拒绝 float、naive datetime、bytes、非字符串对象 key 和任意
Python/BSON 对象。

历史 `{action, data, hmac}` Mongo 文档仅按原编码和 legacy key 只读验证，不自动改写。
它们没有序号和前序 MAC，因此无法追溯证明历史删除或重排。

## Key domain 与轮换

| 用途 | 环境变量 | 规则 |
| --- | --- | --- |
| 冻结 PostgreSQL 历史验证 | `LOGINTEGRITY_HMAC_KEY_BASE64` | 保留历史 key，至少 32 bytes |
| Mongo schema v1 | `MONGO_AUDIT_HMAC_KEY_BASE64` | 活跃 key 正好 32 bytes |
| checkpoint | `CHECKPOINT_AUDIT_HMAC_KEY_BASE64` | 活跃 key 正好 32 bytes |

Key ID 是非秘密版本标签。轮换时新增 key/ID、切换对应 domain 的 active ID、验证新旧样本；
证据保留期结束且批准销毁前不得移除旧验证 key，也不得通过重签旧证据完成轮换。

## Outbox 与幂等契约

1. 业务修改和唯一 `AuditOutbox.event_id` 在同一 PostgreSQL 事务提交。
2. event ID 一旦绑定，`occurred_at`、partition 与完整 canonical event 不得变化。
3. worker claim 生成 `lock_token`；完成/失败更新必须同时匹配 row、processing 状态和 token。
4. receipt 必须含相同 partition、正整数 sequence、非空 MAC；畸形 receipt 保持可重试。
5. 同 event ID 重投只在完整事件和 partition 一致且已有 Mongo HMAC 有效时视为成功。
6. delivered outbox 定期与 Mongo 对账；outbox 不能作为查询 fallback。

## 分区链与 checkpoint

Mongo 事务同时完成 sequence 分配、事件插入和链头推进。链验证检测内容修改、插入、删除、
重复和重排；尾部截断只有相对可信 checkpoint 才可检测。

`--checkpoint` 仅在扫描到当前 Mongo head 且整链有效后写入签名 checkpoint。随后通过
`export_audit_checkpoint` 转移到独立不可变存储。仅存在 PostgreSQL 内的 checkpoint 是
Mongo-external，但不是 external WORM。

## 查询契约

`GET /security/audit-events/` 仅允许 active superuser 或 `security.view_audit_log`；只读 Mongo
schema v1；过滤字段采用字符串白名单，页大小上限 200，使用 `(occurred_at, _id)` cursor，
每条结果附完整性 verdict。Mongo 故障返回 503，不泄露连接串/payload/key，也不读取 outbox。

## 冻结的 PostgreSQL 历史证据

- 新 `LogEntry` 不再生成 `SecureLogEntry`。
- `SecureLogEntry` 禁止修改、删除和重签；校验只更新 verification metadata。
- 补缺必须提供 aware UTC cutoff 与显式 acknowledgement，只创建 cutoff 前缺失行。
- 未知/可疑 HMAC 不覆盖；不得用 force 类参数重建信任基线。

## 明确不记录

密码、session/token、TOTP seed/验证码/恢复码、HMAC key、证书私钥、完整请求体、邮件、
原始 IP/UA/referrer、自由文本审核理由、对象展示值和字段修改值不得进入安全审计事件。
