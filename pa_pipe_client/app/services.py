from __future__ import annotations

from datetime import datetime, timezone
import json
import subprocess
from typing import Any

from .config import Settings
from .models import PortStatus, ProcessStatus, StatusResponse


def _powershell_json(script: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=8,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "PowerShell status probe failed")
    raw = completed.stdout.strip()
    return json.loads(raw) if raw else {}


def probe_windows_state() -> dict[str, Any]:
    script = r"""
$ports = @()
foreach ($p in @(7890, 8890)) {
  $items = @(Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue)
  if ($items.Count -gt 0) { $ports += [pscustomobject]@{ port=$p; protocol='tcp'; listening=$true } }
  else { $ports += [pscustomobject]@{ port=$p; protocol='tcp'; listening=$false } }
}
$udp = @(Get-NetUDPEndpoint -LocalPort 51821 -ErrorAction SilentlyContinue)
$processes = @()
$wstunnelCommands = @()
foreach ($name in @('wstunnel.exe', 'Clash Party.exe')) {
  foreach ($p in @(Get-CimInstance Win32_Process -Filter "Name = '$name'" -ErrorAction SilentlyContinue)) {
    $processes += [pscustomobject]@{ name=$name; pid=[int]$p.ProcessId; running=$true }
    if ($name -eq 'wstunnel.exe') { $wstunnelCommands += [string]$p.CommandLine }
  }
}
$contract = $null
if ($wstunnelCommands.Count -gt 0) {
  $contract = $false
  foreach ($command in $wstunnelCommands) {
    if ($command.Contains('43.165.174.246:443') -and $command.Contains('127.0.0.1:51821') -and $command.Contains('127.0.0.1:51820')) { $contract = $true }
  }
}
[pscustomobject]@{
  tunnel=[pscustomobject]@{ port=51821; protocol='udp'; listening=($udp.Count -gt 0) }
  proxy_ports=$ports
  processes=$processes
  wstunnel_contract=$contract
} | ConvertTo-Json -Depth 4 -Compress
"""
    return _powershell_json(script)


def _port(value: Any, default: int, protocol: str) -> PortStatus:
    return PortStatus(port=int(value.get("port", default)), protocol=protocol, listening=bool(value.get("listening")))


def build_status(settings: Settings) -> StatusResponse:
    now = datetime.now(timezone.utc)
    try:
        raw = probe_windows_state()
        tunnel = _port(raw.get("tunnel", {}), 51821, "udp")
        proxies = [_port(item, 0, "tcp") for item in raw.get("proxy_ports", [])]
        processes = [ProcessStatus.model_validate(item) for item in raw.get("processes", [])]
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return StatusResponse(
            state="unknown", checked_at=now, tunnel=PortStatus(port=51821, protocol="udp", listening=False),
            proxy_ports=[PortStatus(port=7890, protocol="tcp", listening=False), PortStatus(port=8890, protocol="tcp", listening=False)],
            processes=[], wstunnel_contract="unknown", detail=f"状态探针失败：{exc}",
        )

    wstunnel = any(p.name == "wstunnel.exe" for p in processes)
    raw_contract = raw.get("wstunnel_contract")
    contract = "unknown" if raw_contract is None else ("ok" if bool(raw_contract) else "mismatch")
    clash = any(p.name == "Clash Party.exe" for p in processes)
    active_proxy = any(port.listening for port in proxies)
    if contract == "mismatch":
        state, detail = "degraded", "检测到 wstunnel，但命令行不符合 443 → 51821 → 51820 契约，已禁止信任该转发"
    elif tunnel.listening and active_proxy:
        state, detail = "ready", "WSS 转发和本地代理均在监听"
    elif not tunnel.listening and not clash and not active_proxy:
        state, detail = "stopped", "启动链路当前未运行"
    else:
        state, detail = "degraded", f"wstunnel={'运行' if wstunnel else '停止'}，Clash={'运行' if clash else '停止'}"
    return StatusResponse(state=state, checked_at=now, tunnel=tunnel, wstunnel_contract=contract, proxy_ports=proxies, processes=processes, detail=detail)


def read_log_tail(settings: Settings, lines: int = 200) -> list[str]:
    lines = max(1, min(lines, 500))
    if not settings.log_file.is_file():
        return ["日志文件尚不存在。先点击“启动链路”。"]
    try:
        content = settings.log_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"无法读取日志：{exc}"]
    secret = ""
    try:
        secret = settings.secret_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        pass
    result = content.splitlines()[-lines:]
    return [line.replace(secret, "<REDACTED>") if secret else line for line in result]


def _start_args(settings: Settings, restart_clash: bool) -> list[str]:
    args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(settings.start_script)]
    if restart_clash:
        args.append("-RestartClash")
    return args


def start_chain(settings: Settings, restart_clash: bool = False) -> None:
    if not settings.start_script.is_file():
        raise FileNotFoundError(f"找不到启动脚本：{settings.start_script}")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(_start_args(settings, restart_clash), cwd=settings.start_script.parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


def stop_chain(settings: Settings) -> None:
    if not settings.start_script.is_file():
        raise FileNotFoundError(f"找不到启动脚本：{settings.start_script}")
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(settings.start_script), "-Stop"], cwd=settings.start_script.parent, capture_output=True, text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
