"""SK8 Clip 媒体校验：FFprobe 权威探测与规则判定。

安全约束（SKATEBOARD_GUIDE §6/§7）：
- 扩展名 / MIME / 浏览器 metadata 一律不作为安全裁决依据。
- subprocess 只用参数列表，禁 shell 拼接；必须设 timeout。
- 错误信息只保留有界摘要，不回显内部命令或绝对路径。
- 本模块不持数据库连接（FFprobe 运行期间不进事务）。
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


class ClipProbeError:
    """有界错误码（面向管理员展示，映射为固定文案）。"""

    INVALID_CONTAINER = "invalid_container"
    NO_VIDEO_STREAM = "no_video_stream"
    DURATION_MISSING = "duration_missing"
    DURATION_EXCEEDED = "duration_exceeded"
    PROBE_FAILED = "probe_failed"
    PROBE_TIMEOUT = "probe_timeout"


@dataclass(frozen=True)
class ClipProbeResult:
    ok: bool
    error_code: str = ""
    error_detail: str = ""
    duration_ms: int | None = None
    # 显示宽高：coded 尺寸按 displaymatrix 旋转换算后的结果。
    width: int | None = None
    height: int | None = None
    coded_width: int | None = None
    coded_height: int | None = None
    rotation: int | None = None
    frame_rate: str = ""
    has_audio: bool = False
    video_codec: str = ""
    format_name: str = ""


_DETAIL_LIMIT = 200


def _bounded_detail(text: str) -> str:
    return " ".join((text or "").split())[:_DETAIL_LIMIT]


def run_ffprobe(path: Path | str) -> subprocess.CompletedProcess:
    """以参数列表形式执行 ffprobe（JSON 输出），强制 timeout。"""
    return subprocess.run(
        [
            settings.SKATE_CLIP_FFPROBE_PATH,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=settings.SKATE_CLIP_FFPROBE_TIMEOUT,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def _rotation_from_stream(stream: dict) -> int | None:
    for side in stream.get("side_data_list") or []:
        rotation = side.get("rotation")
        if rotation is not None:
            try:
                return int(rotation)
            except (TypeError, ValueError):
                return None
    return None


def _display_dimensions(
    coded_width: int | None, coded_height: int | None, rotation: int | None
) -> tuple[int | None, int | None]:
    """±90°/270° 旋转时互换显示宽高。"""
    if coded_width is None or coded_height is None:
        return None, None
    if rotation in (90, -90, 270, -270):
        return coded_height, coded_width
    return coded_width, coded_height


def _parse_frame_rate(value) -> str:
    """保留 FFprobe 分数文本（如 30000/1001）；退化值归空串。"""
    text = str(value or "").strip()
    if not text or text in ("0/0", "0"):
        return ""
    return text[:32]


def parse_probe_payload(payload: dict) -> ClipProbeResult:
    """把 ffprobe JSON 映射为探测结果并执行规则判定（纯函数，可单测）。"""
    streams = payload.get("streams") or []
    fmt = payload.get("format") or {}
    videos = [s for s in streams if s.get("codec_type") == "video"]
    if not videos:
        return ClipProbeResult(
            ok=False,
            error_code=ClipProbeError.NO_VIDEO_STREAM,
            error_detail="No video stream found.",
            format_name=str(fmt.get("format_name") or "")[:64],
        )
    video = videos[0]
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    raw_duration = fmt.get("duration") or video.get("duration")
    try:
        duration_s = float(str(raw_duration))
    except (TypeError, ValueError):
        duration_s = None
    if duration_s is None or not math.isfinite(duration_s) or duration_s <= 0:
        return ClipProbeResult(
            ok=False,
            error_code=ClipProbeError.DURATION_MISSING,
            error_detail=f"Unparseable duration: {_bounded_detail(str(raw_duration))}",
            format_name=str(fmt.get("format_name") or "")[:64],
            video_codec=str(video.get("codec_name") or "")[:32],
            has_audio=has_audio,
        )
    duration_ms = int(round(duration_s * 1000))
    if duration_ms > settings.SKATE_CLIP_MAX_DURATION_MS:
        return ClipProbeResult(
            ok=False,
            error_code=ClipProbeError.DURATION_EXCEEDED,
            error_detail=f"Duration {duration_ms}ms exceeds limit.",
            duration_ms=duration_ms,
            format_name=str(fmt.get("format_name") or "")[:64],
            video_codec=str(video.get("codec_name") or "")[:32],
            has_audio=has_audio,
        )

    try:
        coded_width = int(video["width"])
        coded_height = int(video["height"])
    except (KeyError, TypeError, ValueError):
        coded_width = coded_height = None

    if coded_width is None or coded_height is None or coded_width <= 0 or coded_height <= 0:
        return ClipProbeResult(
            ok=False,
            error_code=ClipProbeError.NO_VIDEO_STREAM,
            error_detail=f"Invalid video dimensions: {coded_width}x{coded_height}",
            duration_ms=duration_ms,
            format_name=str(fmt.get("format_name") or "")[:64],
            video_codec=str(video.get("codec_name") or "")[:32],
            has_audio=has_audio,
        )

    rotation = _rotation_from_stream(video)
    width, height = _display_dimensions(coded_width, coded_height, rotation)

    return ClipProbeResult(
        ok=True,
        duration_ms=duration_ms,
        width=width,
        height=height,
        coded_width=coded_width,
        coded_height=coded_height,
        rotation=rotation,
        frame_rate=_parse_frame_rate(video.get("r_frame_rate")),
        has_audio=has_audio,
        video_codec=str(video.get("codec_name") or "")[:32],
        format_name=str(fmt.get("format_name") or "")[:64],
    )


def probe_video_file(path: Path | str) -> ClipProbeResult:
    """对磁盘文件执行权威探测：损坏/伪扩展/超时长一律拒绝。"""
    try:
        proc = run_ffprobe(path)
    except subprocess.TimeoutExpired:
        return ClipProbeResult(
            ok=False,
            error_code=ClipProbeError.PROBE_TIMEOUT,
            error_detail="ffprobe timed out.",
        )
    except OSError as exc:
        return ClipProbeResult(
            ok=False,
            error_code=ClipProbeError.PROBE_FAILED,
            error_detail=_bounded_detail(str(exc)),
        )
    if proc.returncode != 0:
        return ClipProbeResult(
            ok=False,
            error_code=ClipProbeError.INVALID_CONTAINER,
            error_detail=_bounded_detail(proc.stderr or "ffprobe failed."),
        )
    try:
        payload = json.loads(proc.stdout or "")
    except json.JSONDecodeError:
        return ClipProbeResult(
            ok=False,
            error_code=ClipProbeError.PROBE_FAILED,
            error_detail="ffprobe returned non-JSON output.",
        )
    return parse_probe_payload(payload)


def sha256_file(path: Path | str, chunk_size: int = 1024 * 1024) -> str:
    """流式计算文件 SHA-256（上传审计与一致性）。"""
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


#: 面向管理员的错误码 → 中文文案映射（不含内部细节）。
CLIP_PROBE_ERROR_MESSAGES = {
    ClipProbeError.INVALID_CONTAINER: "文件无法解析：不是有效的视频容器或已损坏。",
    ClipProbeError.NO_VIDEO_STREAM: "文件中没有视频流。",
    ClipProbeError.DURATION_MISSING: "无法读取视频时长。",
    ClipProbeError.DURATION_EXCEEDED: "视频超过 20 秒上限。",
    ClipProbeError.PROBE_FAILED: "探测失败，请稍后重试。",
    ClipProbeError.PROBE_TIMEOUT: "探测超时，请稍后重试。",
}
