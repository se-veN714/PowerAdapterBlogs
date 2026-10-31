"""PAdif 语义版本标注引导。

设计原则（来自 GUIDE）：仅引导、不强制。
- bump()：依据创作者选择的 major/minor/patch 自动递增版本号。
- suggest_kind()：根据 diff 统计给一个「建议级别」，仅供创作者参考。
- gentle_warn()：检测「几乎无变化」时返回 True，由上层决定是否给出温和提醒（不阻断提交）。
"""

from __future__ import annotations

import re
from typing import Optional

_KIND_WEIGHT = {"major": 0, "minor": 1, "patch": 2}

# 用于「去噪」比较的标点/空白集合
_NOISE = re.compile(r"[\s，。！？、；：,.!?;:\"'\-—…（）()\[\]【】]")


def _parse(version: str) -> tuple[int, int, int]:
    parts = (version or "0.0.0").split(".")
    nums = [int(p) if p.isdigit() else 0 for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]


def bump(prev: Optional[str], kind: str) -> str:
    """按级别递增版本号。无前序版本时，首版固定为 1.0.0。"""
    if not prev:
        return "1.0.0"
    major, minor, patch = _parse(prev)
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    # patch（默认）
    return f"{major}.{minor}.{patch + 1}"


def suggest_kind(diff_stats: dict) -> str:
    """根据增删规模给一个建议级别（仅建议，不强制）。"""
    added = diff_stats.get("sentences_added", 0)
    removed = diff_stats.get("sentences_removed", 0)
    total = added + removed
    if total >= 8:
        return "major"
    if total >= 3:
        return "minor"
    return "patch"


def gentle_warn(a: str, b: str) -> bool:
    """若两版在「去噪」后实质相同，返回 True（提示创作者，但不阻断）。"""
    if a == b:
        return True
    na = _NOISE.sub("", a)
    nb = _NOISE.sub("", b)
    return na == nb and na != ""
