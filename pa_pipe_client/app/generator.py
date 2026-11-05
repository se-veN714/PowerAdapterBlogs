from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .config import Settings


class ProfileGenerationError(ValueError):
    """The source profile does not satisfy the PA-pipe port contract."""


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileGenerationError(f"{label} 不是 YAML 对象")
    return value


def generate_profile(settings: Settings) -> tuple[Path, dict[str, str]]:
    """Create a standalone Mihomo profile without exposing the private key."""
    if not settings.profile_template.is_file():
        raise FileNotFoundError(f"找不到 Mihomo 模板：{settings.profile_template}")
    source = yaml.safe_load(settings.profile_template.read_text(encoding="utf-8"))
    data = _require_mapping(source, "profile")
    proxies = data.get("proxies")
    if not isinstance(proxies, list):
        raise ProfileGenerationError("模板没有 proxies 列表")
    pipe = next((item for item in proxies if isinstance(item, dict) and item.get("name") == "PA-pipe"), None)
    pipe = _require_mapping(pipe, "PA-pipe proxy")
    if pipe.get("type") != "wireguard":
        raise ProfileGenerationError("PA-pipe 节点不是 wireguard 类型")
    peers = pipe.get("peers")
    if not isinstance(peers, list) or not peers:
        raise ProfileGenerationError("PA-pipe 节点没有 peer")
    peer = _require_mapping(peers[0], "PA-pipe peer")

    # This is the only valid local hand-off. The WSS server address belongs to
    # Start-PA-pipe.ps1 and must never be copied into the WireGuard endpoint.
    peer["server"] = "127.0.0.1"
    peer["port"] = 51821
    peer["allowed-ips"] = ["0.0.0.0/0"]
    pipe["udp"] = True
    pipe["mtu"] = 1280
    data["mixed-port"] = 7890
    data["allow-lan"] = False
    data["bind-address"] = "127.0.0.1"
    data["ipv6"] = False
    tun = _require_mapping(data.setdefault("tun", {}), "tun")
    tun["enable"] = False
    tun["route-exclude-address"] = ["43.165.174.246/32"]

    if peer["server"] != "127.0.0.1" or int(peer["port"]) != 51821:
        raise ProfileGenerationError("生成后的 WireGuard endpoint 不符合 127.0.0.1:51821 契约")
    if not str(pipe.get("private-key", "")).strip():
        raise ProfileGenerationError("模板缺少 private-key，无法生成可导入配置")

    settings.generated_dir.mkdir(parents=True, exist_ok=True)
    filename = f"PA-pipe-Mihomo-generated-{datetime.now():%Y%m%d-%H%M%S}.yaml"
    target = settings.generated_dir / filename
    target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return target, {"wss": "43.165.174.246:443/TCP", "wstunnel_udp": "127.0.0.1:51821/UDP", "mihomo": "127.0.0.1:7890/TCP", "tun": "disabled"}
