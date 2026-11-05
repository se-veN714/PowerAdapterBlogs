from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ProcessStatus(BaseModel):
    name: str
    pid: int
    running: bool = True


class PortStatus(BaseModel):
    port: int
    protocol: Literal["tcp", "udp"]
    listening: bool


class StatusResponse(BaseModel):
    state: Literal["ready", "degraded", "stopped", "unknown"]
    checked_at: datetime
    tunnel: PortStatus
    wstunnel_contract: Literal["ok", "mismatch", "unknown"] = "unknown"
    proxy_ports: list[PortStatus]
    processes: list[ProcessStatus]
    detail: str


class LogsResponse(BaseModel):
    path: str
    lines: list[str]
    truncated: bool = False


class ActionRequest(BaseModel):
    restart_clash: bool = False


class ActionResponse(BaseModel):
    action: Literal["start", "stop", "restart"]
    accepted: bool
    message: str


class ProfileResponse(BaseModel):
    filename: str
    path: str
    download_url: str
    contract: dict[str, str]
