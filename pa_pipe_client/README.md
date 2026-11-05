# PA-pipe 本地管理客户端

这是一个只绑定 `127.0.0.1` 的 FastAPI 管理面板，负责查看 PA-pipe 的
`wstunnel`、Clash Party、7890/8890 端口和 WSS 守护日志，并调用现有的
`Start-PA-pipe.ps1` 启停脚本。它沿用 Dionysus Console 的边界：浏览器只访问
HTTP/SSE 投影，不能直接读文件、环境变量或运行任意命令。

## 启动

在 Windows PowerShell 中：

```powershell
cd D:\Work\Project\DjangoProject\pa_pipe_client
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8744
```

也可以双击 `Start-PA-pipe-Client.cmd`。面板地址是
<http://127.0.0.1:8744>。

如果路径不同，可以设置：

```powershell
$env:PA_PIPE_HOME = 'C:\Users\12442\Desktop\script\PA-pipe-wstunnel'
$env:PA_PIPE_START_SCRIPT = 'C:\Users\12442\Desktop\script\Start-PA-pipe.ps1'
$env:PA_PIPE_LOG = 'C:\Users\12442\Desktop\script\PA-pipe-wstunnel\logs\wstunnel-supervisor.log'
```

## 页面操作

- **启动链路**：调用现有启动脚本；它会启动 wstunnel 守护进程和 Clash Party。
- **停止转发**：只调用现有 `-Stop`，不会关闭 Clash Party。
- **重启链路**：先停止 wstunnel，再重新启动；可勾选同时重启 Clash Party。
- **日志**：只返回末尾有限行，并遮盖本地 WSS 路径密钥。

客户端默认只监听回环地址，不应改成 `0.0.0.0`，也不应把控制端口放进腾讯云安全组。
