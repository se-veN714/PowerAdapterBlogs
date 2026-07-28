# `/super_admin/` Client CA 运维手册

> 文档权重：90（H3 TLS 1.3 mTLS 生产运维契约）

本目录只保存可公开评审的模板。CA 私钥、客户端私钥、签发数据库、CSR、证书、PKCS#12、CRL 和口令不得在仓库内生成或保存。所有示例中的 `PA_CLIENT_CA_DIR` 必须指向仓库外的加密离线介质或受限目录。

## 1. 固定边界

- 生产 profile 仅为 `standard-tls`，Nginx 仅允许 TLS 1.3。
- Nginx 和离线 CA 命令行统一使用仍受支持的 OpenSSL 4.0.x 最新补丁版；初始基线为 4.0.1。4.0 是非 LTS，因此每次 OpenSSL 安全更新都必须及时跟进，且在 2027-05-14 前重新选择受支持分支。
- 公网服务器证书继续由 Let’s Encrypt 签发；私有 Client CA 只签发 `clientAuth` 客户端证书。
- Root Client CA 私钥保持离线，不上传服务器。服务器只部署 CA 公钥证书与当前 CRL。
- 客户端私钥应在管理员终端生成并以有密码的 PKCS#12/系统证书容器保存，不通过聊天、邮件或 Git 传输。
- Django 不保存 PEM 或私钥，只绑定 Nginx 实际上报的 issuer DN、serial、subject DN、profile 和有效期。

## 2. 离线 CA 初始化

以下命令只允许在离线 CA 环境执行。先复制 `openssl-client-ca.cnf.example` 到仓库外，再初始化权限受限的 CA 目录：

```text
PA_CLIENT_CA_DIR/
  private/ca.key.pem       # 离线、加密、最严格权限
  ca.crt.pem               # 可部署的公钥证书
  index.txt                # OpenSSL CA 数据库
  serial / crlnumber
  newcerts/
```

使用 OpenSSL 4.0.x 最新补丁版生成至少 3072-bit、口令加密的 RSA CA 私钥，再以模板的 `v3_ca` 扩展签发 Root CA。CA 有效期建议 5 年；客户端叶证书默认 180 天。不要使用 `-nodes` 或 `-noenc` 创建 CA 私钥。OpenSSL 主版本升级不要求重新签发仍安全有效的证书，但 CA 操作和 CRL 生成必须先在备份副本上回归。

初始化后立即生成一份空 CRL，并把 `ca.crt.pem` 与 CRL 的只读副本交给 Nginx。私钥介质离线保存，同时保留一份独立加密备份；备份恢复必须在启用强制 mTLS 前演练。

## 3. 客户端签发与绑定

1. 管理员终端本地生成有口令保护的私钥和 CSR；CSR 的 CN 使用稳定用户名或设备标识，但 CN 本身不授予 Django 权限。
2. 离线 CA 检查 CSR 后用 `openssl ca` 和 `client_cert` 扩展签发；禁止 CSR 自带扩展覆盖模板。
3. 检查叶证书必须包含 `CA:FALSE`、`Digital Signature` 和 `TLS Web Client Authentication`，且不包含服务端用途。
4. 导出有强口令的 PKCS#12 并导入 Chrome/Edge 所使用的系统证书容器；完成后安全删除中转文件。
5. 先在管理 vhost 完成一次真实握手，记录 Nginx `$ssl_client_serial`、`$ssl_client_i_dn`、`$ssl_client_s_dn` 的实际值，再执行绑定命令。不要凭手工重排 DN：

```text
python manage.py bind_client_certificate \
  --username <target-superuser> \
  --actor <approving-superuser> \
  --serial <nginx-ssl-client-serial> \
  --issuer-dn <nginx-ssl-client-i-dn> \
  --subject-dn <nginx-ssl-client-s-dn> \
  --expires-at <timezone-aware-ISO-8601>
```

`--profile` 默认为且仅允许 `standard-tls`。绑定成功不等于开启强制认证；生产开关在全部验收完成前保持关闭。

## 4. 轮换

1. 在旧证书到期前签发具有新 serial 的证书。
2. 保留旧绑定，新增并测试新绑定；确认新证书能完成 mTLS、密码和 TOTP 三道认证。
3. 使用 `revoke_client_certificate --reason rotated` 撤销旧 Django 绑定，使旧 privileged Session 立即失效。
4. 离线 CA 撤销旧证书并重新生成 CRL；以原子替换方式部署 CRL，执行 `nginx -t` 后 reload。
5. 验证旧证书在 Nginx 层被拒绝，新证书仍可登录，再销毁旧客户端私钥。

## 5. 丢失或疑似泄露

处理顺序以尽快切断访问为目标：

1. 通过受控 SSH/控制台执行 Django 绑定撤销，reason 使用 `lost` 或 `suspected_compromise`。
2. 在离线 CA 数据库中撤销证书并生成新 CRL。
3. 原子部署 CRL，`nginx -t` 成功后 reload。
4. 验证旧证书无法建立新 TLS 连接，也无法继续使用旧 privileged Session。
5. 审计 Django HMAC 日志、Nginx access/error log 和异常登录记录，按轮换流程签发替代证书。

只撤销 Django 绑定不能阻止 TLS 握手，只更新 CRL 也不能使已经签发的 Django privileged Session 立即失效；两层必须同时完成。

## 6. Break-glass 与回滚

- 唯一管理员不得把恢复能力全部放在同一台手机或电脑上。至少保留离线 TOTP 恢复码、离线 Client CA 恢复材料和服务器控制台/SSH 三类路径。
- 日常运维统一经 Tailscale Tailnet 进入，再使用专用非 root 账号、SSH key 与按需 `sudo`；公网安全组不为 Agent 临时出口 IP 长期开 SSH，也不把宽泛地区加入云主机安全白名单。
- break-glass 不建立公网的无 mTLS 平行入口。通过云控制台或 Tailscale 内受限 SSH 修改配置，并把临时入口限制在 loopback、Tailnet 或明确的固定管理地址。
- 应用回滚可以关闭 `MTLS_ENFORCEMENT_ENABLED`，但必须同时确保公网 `/super_admin/` 仍被 Nginx 拒绝；修复后重新运行完整 readiness。
- 所有演练记录时间、执行人、结果码和后续动作，不记录口令、私钥、TOTP seed/code 或完整证书。

## 7. 上线验收

完成真实浏览器、Client CA、CRL、独立 Nginx vhost 与 break-glass 演练后执行：

```text
python manage.py check_mtls_readiness \
  --acknowledge-proxy-boundary \
  --acknowledge-client-ca \
  --acknowledge-revocation \
  --acknowledge-break-glass \
  --acknowledge-openssl-4
```

先在服务器运行 `sh deploy/nginx/check_mtls_edge.sh`，保存 `nginx -V`、`openssl version` 与 `nginx -t` 的输出作为版本证据。随后再运行上述 Django readiness。readiness 只验证应用配置、所有 active superuser 的有效绑定和人工验收声明，不会读取或证明私钥安全，也不能代替真实 TLS 握手测试。命令通过后，才允许开启 `MTLS_ENFORCEMENT_ENABLED=true`。

## 8. 当前验证证据

2026-07-29 已使用 Windows VC-WIN64A OpenSSL 4.0.1 对本模板完成开发材料测试：Root CA 自签、3072-bit RSA 客户端 CSR、`clientAuth`-only 叶证书签发、证书链验证、PKCS#12 导出、CA 撤销、CRL 重发以及 `-crl_check` 拒绝均通过。撤销后的证书按预期返回 X.509 error 23。测试材料位于仓库已忽略的 `.local/mtls-openssl-4-test/`，口令固定且仅用于开发，不能导入生产或充当 break-glass 材料。

该证据只覆盖 OpenSSL CA/CRL 工具链，不代表 Nginx 已链接 OpenSSL 4.0.x，也不代表 Chrome/Edge 握手、Django 绑定或生产吊销链已经验收。
