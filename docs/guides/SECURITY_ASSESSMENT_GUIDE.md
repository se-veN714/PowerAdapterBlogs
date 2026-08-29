# 信息服务安全评估整改指南

> 文档权重：90。记录 PowerAdapter 针对当前公开博客、评论与短视频展示能力的实际控制和未完成事项。本文是工程自查记录，不替代主管部门意见或专业法律意见。

## 1. 适用依据

- 《具有舆论属性或社会动员能力的互联网信息服务安全评估规定》将博客、短视频、信息分享及附设相关功能纳入评估范围，并要求评估身份核验、注册信息、日志留存、违法有害信息处置和投诉举报等措施。
- 《互联网跟帖评论服务管理规定》要求跟帖评论实行“后台实名、前台自愿”，建立审核、处置留痕、公众投诉举报和用户申诉机制。
- 《中华人民共和国网络安全法》要求采取监测、记录网络运行状态和网络安全事件的技术措施，并按规定留存相关网络日志不少于六个月。

官方原文：

- <https://www.cac.gov.cn/2019-03/20/c_1124259405.htm>
- <https://www.cac.gov.cn/2022-11/16/c_1670253725725039.htm>
- <https://www.npc.gov.cn/zgrdw/npc/zfjc/zfjcelys/2016-11/07/content_2034939.htm>

## 2. 2026-08-29 已实现控制

### 2.1 评论真实身份门禁

- `MyUser` 只保存核验方式、核验时间和核验操作人，不保存手机号、证件号或统一社会信用代码原文。
- 仅 superuser 可在完成线下或外部核验后选择法定支持的核验方式；选择动作构成管理员的核验确认。
- 未完成核验的账号可登录和浏览，但服务端拒绝评论提交；前端同时隐藏评论输入框。前端限制不是安全边界。
- 评论创建审计保存账号、时间、文章、状态、网络源地址和浏览器弱指纹，不将评论正文写入审计事件。

### 2.2 公众投诉举报与申诉闭环

- `/reports/new/` 对公众开放，覆盖违法或不良信息、侵权、隐私、垃圾信息、内容处置申诉及其他问题。
- 每次有效提交生成随机 UUID 受理编号；`/reports/<reference>/` 仅展示最小状态、目标位置和公开反馈，不展示问题正文、联系邮箱、来源摘要或内部记录，并发送 `private, no-store`。
- 目标位置只接受本站绝对路径，拒绝外部 URL；按来源地址摘要限流。
- 新建和后台处置均写入事务型安全审计 outbox；审计事件不包含举报正文和联系邮箱。
- super_admin 可将事项推进为待受理、处理中、已处理或不予处理，并填写内部记录与公开反馈。

### 2.3 六个月日志留存

- 生产应用进程使用 `WatchedFileHandler`，只负责写入；宿主 `logrotate` 按日轮换并保留 183 份，避免多 Gunicorn worker 竞争改名归档。
- Web、prepare、audit-worker、skate-worker 使用不同文件名前缀；根 logger 与 `django.request` 均接入持久文件，不只保留 `Blogs/security` 日志。
- Nginx 公网与管理域名使用独立 access/error 日志；`deploy/logrotate/poweradapter-nginx` 按日保留 183 份并压缩。
- `deploy/var/logs` 和 `/var/log/nginx/poweradapter-*.log` 必须进入备份与恢复演练。Docker/Gunicorn stdout 只是诊断副本，不作为六个月留存证据。

## 3. 仍需人工或后续迭代的事项

1. **部署动作**：在生产主机安装并 dry-run 检查 application 与 Nginx 两份 logrotate 配置；仅提交文件不能证明主机已执行或备份已覆盖。
2. **存量账号核验**：迁移不会自动把任何普通用户标记为已核验。站点所有者必须依据真实核验结果逐个确认；不得为通过测试而批量补标。
3. **投稿者范围**：本阶段硬门禁覆盖评论。Board 投稿账号本身为管理员邀请和审批用户，但仍需在下一阶段决定是否把同一真实身份状态前置到 Board Membership 与内容创建策略。
4. **处理制度**：代码提供受理、处置和反馈能力；站点所有者仍需实际巡查队列、及时处理、保存处置依据，并确定可执行的响应时限。
5. **申报措辞**：安全评估表只能描述已经部署并实际执行的措施。未安装 logrotate、未核验存量账号或未形成巡查制度前，不得填写为“已完成”。

## 4. 发布前验收

```powershell
.\.local\test-env\Scripts\python.exe manage.py test config.tests_content_reports config.tests_log_retention comment.tests
.\.local\test-env\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.local\test-env\Scripts\python.exe manage.py check
```

生产主机：

```bash
sudo install -o root -g root -m 0644 deploy/logrotate/poweradapter-nginx /etc/logrotate.d/poweradapter-nginx
sudo install -o root -g root -m 0644 deploy/logrotate/poweradapter-application /etc/logrotate.d/poweradapter-application
sudo logrotate --debug /etc/logrotate.d/poweradapter-nginx
sudo logrotate --debug /etc/logrotate.d/poweradapter-application
```
