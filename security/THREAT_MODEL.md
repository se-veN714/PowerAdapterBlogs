# Security Audit Threat Model

> **文档权重**：94（安全边界与覆盖矩阵）
>
> **最后更新**：2026-08-26

## 保护目标

系统需要回答：谁在何时对哪个稳定目标执行了什么安全相关状态修改、结果如何，以及事件是否
被修改、插入、重复、删除、重排或截断；还需识别已提交但仍未投递到 Mongo 的业务事件。

审计证据不等于诊断日志。密码、密钥、MFA 秘密、证书私钥、完整请求、邮件、原始客户端
元数据和自由文本不是审计资产，不得复制进事件。

## 攻击者与信任边界

假设攻击者可能获得应用进程权限、修改或重放 Mongo 文档、阻断投递，或读取普通应用日志。
数据库/主机管理员能越过应用层防护，因此最小权限、备份、Mongo oplog/监控、独立 checkpoint
存储分别构成额外信任边界。

PostgreSQL 与 Mongo 无法参加同一可移植事务：业务事务 + PostgreSQL outbox 是提交耐久边界；
Mongo 事务是事件插入 + 链头推进边界。Mongo standalone 不满足该保证。

HMAC 仅在用途密钥保密时检测修改；持有 key 的人可以伪造历史。分区链只能检测被观察分区内
的修改/插删/重排；尾部截断依赖 Mongo 外 checkpoint，且 PostgreSQL checkpoint 不等于 WORM。

## 当前覆盖矩阵

| 高价值变化 | 覆盖 | 仍存在的边界 |
| --- | --- | --- |
| Django Admin create/update/delete | 单条 post-save + bulk hook，原子入队最小化事件 | 直接 ORM/SQL 写不属于 Admin 覆盖 |
| 评论创建、审核、软删除 | 业务状态与 outbox 同事务 | 被拒绝且未提交的请求仅属安全遥测 |
| 板块申请审批、Membership 角色/启停/交接 | 服务层显式 outbox，与 relational event 同事务 | 绕开 service 的直接 ORM/SQL 不覆盖 |
| TOTP 绑定、确认、验证、恢复、撤销 | MFA service 显式最小化 outbox | 事务整体回滚的失败事件需独立遥测补充 |
| mTLS 绑定与撤销 | mTLS service 显式最小化 outbox | 反向代理拒绝只写枚举诊断日志 |
| 新 Admin LogEntry | Mongo 为正式权威；不再创建 SecureLogEntry | Django LogEntry 只是框架历史 |
| 历史 PostgreSQL/Mongo 证据 | legacy key 只读验证，不重签 | 旧 Mongo 无链，不能追溯证明删除/重排 |

## 生命周期

1. 显式服务构造 schema v1、白名单、canonical 事件。
2. 业务修改与 outbox 原子提交。
3. worker 以租约领取，按 event ID 幂等投递。
4. Mongo 事务分配 sequence、写 previous MAC、插入事件并推进 head。
5. verifier 有界验证完整 envelope 与链关系。
6. delivered outbox 与 Mongo 定期对账；完整扫描后生成并外部保存 checkpoint。

## 不提供的保证

- 普通滚动日志不是防篡改证据。
- model signal 不能替代数据库权限，也不能捕获直接 SQL。
- PostgreSQL 与 Mongo 同时失陷时，本地 checkpoint 不能提供独立证明。
- checkpoint 导出接口不代表部署已经完成 WORM 保存。
- outbox 投递前是受信任的事务暂存区，不是第二个正式审计库。
- 当前实现是个人项目的合规自我实践，不能单凭代码宣称已通过国家商用密码应用安全性评估。
