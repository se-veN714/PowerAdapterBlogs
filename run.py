# -*- coding: utf-8 -*-
"""使用 Waitress 启动本地站点，并防止重复启动残留服务。"""

from __future__ import annotations

import argparse
import os
import signal
import time
from pathlib import Path
from types import TracebackType


PROJECT_ROOT = Path(__file__).resolve().parent
PID_FILE = PROJECT_ROOT / ".local" / "run.pid"
PID_FIELD_SIZE = 32
LOCK_OFFSET = 1024


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        with SingleInstanceLock(PID_FILE, replace_existing=args.replace_existing):
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
    except KeyboardInterrupt:
        print("\n服务已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
