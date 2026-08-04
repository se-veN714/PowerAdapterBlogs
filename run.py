# -*- coding: utf-8 -*-
"""使用 Waitress 启动本地站点，并防止重复启动残留服务。"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path
from types import TracebackType


PROJECT_ROOT = Path(__file__).resolve().parent
PID_FILE = PROJECT_ROOT / ".local" / "run.pid"
PID_FIELD_SIZE = 32
LOCK_OFFSET = 1024
LOCAL_MTLS_ROOT = PROJECT_ROOT / ".local" / "nginx-mtls"
LOCAL_KEYRING_FILE = LOCAL_MTLS_ROOT / "local-secrets" / "mfa-keyring.json"
LOCAL_NGINX_CONFIG = LOCAL_MTLS_ROOT / "nginx-local-mtls.conf"
LOCAL_NGINX_START = LOCAL_MTLS_ROOT / "start-nginx.ps1"


class AlreadyRunningError(RuntimeError):
    """同一项目的 ``run.py`` 已经持有进程锁。"""


class SingleInstanceLock:
    """持有一个随进程退出自动释放的跨平台文件锁。"""

    def __init__(self, path: Path, *, replace_existing: bool = True):
        self.path = path
        self.replace_existing = replace_existing
        self.file = None

    def _lock(self) -> None:
        self.file.seek(LOCK_OFFSET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _owner_pid(self) -> int | None:
        try:
            self.file.seek(0)
            owner = self.file.read(PID_FIELD_SIZE).decode("ascii").strip("\0\r\n ")
        except OSError:
            return None
        try:
            return int(owner)
        except ValueError:
            return None

    def __enter__(self) -> "SingleInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.file = self.path.open("r+b")
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() <= LOCK_OFFSET:
            self.file.seek(LOCK_OFFSET)
            self.file.write(b"\0")
            self.file.flush()

        try:
            self._lock()
        except OSError as exc:
            owner_pid = self._owner_pid()
            if not self.replace_existing or owner_pid is None:
                self.file.close()
                self.file = None
                raise AlreadyRunningError(
                    f"run.py 已在运行（PID: {owner_pid or 'unknown'}）。"
                ) from exc

            print(f"正在停止旧服务（PID: {owner_pid}）...")
            try:
                os.kill(owner_pid, signal.SIGTERM)
            except OSError as stop_error:
                self.file.close()
                self.file = None
                raise AlreadyRunningError(
                    f"无法停止旧服务（PID: {owner_pid}）。"
                ) from stop_error

            deadline = time.monotonic() + 5
            while True:
                time.sleep(0.1)
                try:
                    self._lock()
                    break
                except OSError as retry_error:
                    if time.monotonic() >= deadline:
                        self.file.close()
                        self.file = None
                        raise AlreadyRunningError(
                            f"旧服务未在 5 秒内退出（PID: {owner_pid}）。"
                        ) from retry_error

        self.file.seek(0)
        self.file.write(f"{os.getpid():<{PID_FIELD_SIZE}}".encode("ascii"))
        self.file.flush()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.file is None:
            return
        try:
            self.file.seek(0)
            self.file.write(b" " * PID_FIELD_SIZE)
            self.file.flush()
            self.file.seek(LOCK_OFFSET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
            self.file = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 PowerAdapterBlogs 本地服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument(
        "--no-replace",
        action="store_false",
        dest="replace_existing",
        help="发现已有 run.py 时拒绝启动，而不是自动替换旧服务",
    )
    security_mode = parser.add_mutually_exclusive_group()
    security_mode.add_argument(
        "--enrollment-mode",
        action="store_true",
        help="加载本地 MFA 密钥但暂时关闭强制，仅用于绑定或恢复设备",
    )
    security_mode.add_argument(
        "--plain",
        action="store_true",
        help="显式使用普通 HTTP 开发模式，不加载本地 MFA/mTLS 配置",
    )
    return parser.parse_args()


def _proxy_auth_secret() -> str:
    try:
        config = LOCAL_NGINX_CONFIG.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            "本地 mTLS Nginx 配置不存在；如需普通调试请显式使用 --plain。"
        ) from exc
    match = re.search(
        r"proxy_set_header\s+X-PA-Proxy-Auth\s+([^;\s]+)\s*;",
        config,
        flags=re.IGNORECASE,
    )
    if match is None or len(match.group(1)) < 32:
        raise RuntimeError("本地 mTLS 代理认证值缺失或长度不足。")
    return match.group(1)


def _configure_local_security(*, enrollment_mode: bool) -> None:
    try:
        keyring_configuration = json.loads(
            LOCAL_KEYRING_FILE.read_text(encoding="utf-8")
        )
        keyring = keyring_configuration["keyring"]
        active_key_id = str(keyring_configuration["active_key_id"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "本地 MFA keyring 不可用；请先运行 initialize-local-mfa-keyring.ps1，"
            "或显式使用 --plain。"
        ) from exc
    if not isinstance(keyring, dict) or active_key_id not in keyring:
        raise RuntimeError("本地 MFA keyring 结构无效。")

    enabled = "false" if enrollment_mode else "true"
    os.environ.update(
        {
            "PROJECT_PROFILE": "develop",
            "MFA_TOTP_KEYRING_JSON": json.dumps(keyring, separators=(",", ":")),
            "MFA_TOTP_ACTIVE_KEY_ID": active_key_id,
            "MFA_TOTP_ISSUER": "PowerAdapter Local",
            "MFA_ENFORCEMENT_ENABLED": enabled,
            "MTLS_ENFORCEMENT_ENABLED": enabled,
            "MTLS_ADMIN_HOST": "admin.localhost",
            "MTLS_TRUSTED_PROXY_NETWORKS": "127.0.0.1/32",
            "MTLS_TRUST_UNIX_SOCKET_PROXY": "false",
            "MTLS_CERTIFICATE_PROFILE": "standard-tls",
            "MTLS_PROXY_AUTH_SECRET": _proxy_auth_secret(),
        }
    )


def _local_nginx_is_listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8443), timeout=0.25):
            return True
    except OSError:
        return False


def _ensure_local_nginx() -> None:
    if _local_nginx_is_listening():
        return
    if not LOCAL_NGINX_START.is_file():
        raise RuntimeError("本地 Nginx 启动脚本不存在。")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(
        (
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LOCAL_NGINX_START),
        ),
        check=True,
        cwd=PROJECT_ROOT,
        creationflags=creation_flags,
    )
    deadline = time.monotonic() + 5
    while not _local_nginx_is_listening():
        if time.monotonic() >= deadline:
            raise RuntimeError("本地 Nginx 未能在 5 秒内监听 8443。")
        time.sleep(0.1)


def main() -> int:
    args = parse_args()
    try:
        with SingleInstanceLock(PID_FILE, replace_existing=args.replace_existing):
            if args.plain:
                os.environ.update(
                    {
                        "PROJECT_PROFILE": "develop",
                        "MFA_ENFORCEMENT_ENABLED": "false",
                        "MTLS_ENFORCEMENT_ENABLED": "false",
                    }
                )
                print("已显式启用普通 HTTP 调试模式；本地 MFA/mTLS 强制关闭。")
            else:
                _configure_local_security(enrollment_mode=args.enrollment_mode)
                _ensure_local_nginx()
                mode = "绑定模式" if args.enrollment_mode else "MFA + mTLS 强制模式"
                print(f"本地安全入口已启用（{mode}）：https://admin.localhost:8443/")

            from waitress import create_server

            from PowerAdapterBlogs.wsgi import application

            server = create_server(application, host=args.host, port=args.port)
            server.print_listen("Serving on http://{}:{}")

            def request_shutdown(signum, frame):
                raise KeyboardInterrupt

            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, request_shutdown)

            try:
                server.run()
            finally:
                server.close()
    except AlreadyRunningError as exc:
        print(exc)
        return 1
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"启动失败：{exc}")
        return 1
    except KeyboardInterrupt:
        print("\n服务已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
