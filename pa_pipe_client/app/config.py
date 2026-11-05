from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    tunnel_home: Path
    start_script: Path
    log_file: Path
    secret_file: Path
    clash_exe: Path
    profile_template: Path
    generated_dir: Path
    host: str = "127.0.0.1"
    port: int = 8744

    @classmethod
    def from_environment(cls) -> "Settings":
        home = Path(os.environ.get("PA_PIPE_HOME", r"C:\Users\12442\Desktop\script\PA-pipe-wstunnel"))
        return cls(
            tunnel_home=home,
            start_script=Path(os.environ.get("PA_PIPE_START_SCRIPT", r"C:\Users\12442\Desktop\script\Start-PA-pipe.ps1")),
            log_file=Path(os.environ.get("PA_PIPE_LOG", str(home / "logs" / "wstunnel-supervisor.log"))),
            secret_file=Path(os.environ.get("PA_PIPE_SECRET", r"C:\Users\12442\Desktop\script\PA-pipe-wstunnel-path.txt")),
            clash_exe=Path(os.environ.get("PA_PIPE_CLASH", r"D:\Tools\mihomo\Clash Party\Clash Party.exe")),
            profile_template=Path(os.environ.get("PA_PIPE_PROFILE", r"C:\Users\12442\AppData\Roaming\mihomo-party\profiles\1a114f1846c.yaml")),
            generated_dir=Path(os.environ.get("PA_PIPE_GENERATED_DIR", r"C:\Users\12442\Downloads\PA-pipe-generated")),
            host=os.environ.get("PA_PIPE_CLIENT_HOST", "127.0.0.1"),
            port=int(os.environ.get("PA_PIPE_CLIENT_PORT", "8744")),
        )
