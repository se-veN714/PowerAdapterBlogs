"""SK8 S2 处理 Worker：FFmpeg 派生 main/preview/poster 并原子发布。

安全与可靠性约束（SKATEBOARD_GUIDE §6/§8 + Review §10）：
- 并发互斥：select_for_update(skip_locked=True) 原子领取，多进程安全。
- Claim 所有权：每次领取生成新 token + 递增 generation；写回时条件
  UPDATE 必须匹配 (pk, processing, generation, token)，不匹配即 stale，
  丢弃输出且不改状态。上传替换时 invalidate_claim 使旧 Worker 失效。
- 幂等：只处理 state=uploaded；ready 直接跳过；失败可由复位或重新上传驱动。
- 崩溃可恢复：claimed_at 超时视为卡死，reset_stuck_media 复位回 uploaded。
- 临时输出写到含 generation 的版本目录；全部校验通过后条件 UPDATE
  一次性切换三个 FileField，旧 ready 资源在确认 stale 后才清理。
- FFmpeg 运行期间不持数据库事务；错误只保留有界摘要。
- subprocess 一律参数列表 + timeout，禁 shell。
- 异常分类：TimeoutExpired / OSError / 意外异常均有明确错误码。
"""

from __future__ import annotations

import os
import subprocess
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from boards.models import SkateClipMedia, SkateClipMediaState, skate_delivery_storage
from boards.skate_media import probe_video_file


class WorkerError:
    """有界错误码（Worker 写入 media.error_code）。"""

    SOURCE_MISSING = "source_missing"
    ENCODE_MAIN_FAILED = "encode_main_failed"
    ENCODE_PREVIEW_FAILED = "encode_preview_failed"
    ENCODE_POSTER_FAILED = "encode_poster_failed"
    DERIVED_INVALID = "derived_invalid"
    PROMOTE_FAILED = "promote_failed"
    FFMPEG_TIMEOUT = "ffmpeg_timeout"
    FFMPEG_NOT_FOUND = "ffmpeg_not_found"
    WORKER_UNEXPECTED = "worker_unexpected"
    STALE_CLAIM = "stale_claim"


_DETAIL_LIMIT = 200


def _bounded(text: str) -> str:
    return " ".join((text or "").split())[:_DETAIL_LIMIT]


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    """执行 FFmpeg；调用者捕获 TimeoutExpired 和 OSError。"""
    return subprocess.run(
        [settings.SKATE_CLIP_FFMPEG_PATH, "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        timeout=settings.SKATE_CLIP_FFMPEG_TIMEOUT,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def claim_next_media() -> SkateClipMedia | None:
    """原子领取一条 uploaded 媒体（多进程互斥）。"""
    with transaction.atomic():
        media = (
            SkateClipMedia.objects.select_for_update(skip_locked=True)
            .filter(state=SkateClipMediaState.UPLOADED)
            .order_by("pk")
            .first()
        )
        if media is None:
            return None
        if SkateClipMedia.objects.claim(media):
            return media
        return None


def claim_media_by_pk(media_id: int) -> SkateClipMedia | None:
    """原子领取指定 pk 的 uploaded 媒体（--media-id 安全路径）。"""
    return SkateClipMedia.objects.claim_by_pk(media_id)


def reset_stuck_media() -> int:
    """把卡死（processing 超时）的媒体复位回 uploaded，返回复位数量。"""
    cutoff = timezone.now() - timedelta(seconds=settings.SKATE_CLIP_STUCK_PROCESSING_SECONDS)
    with transaction.atomic():
        qs = (
            SkateClipMedia.objects.select_for_update(skip_locked=True)
            .filter(state=SkateClipMediaState.PROCESSING, claimed_at__lt=cutoff)
        )
        return qs.update(
            state=SkateClipMediaState.UPLOADED,
            claimed_at=None,
            error_code="",
            error_detail="",
        )


# ---------------------------------------------------------------------------
# 派生配方（参数由 .local/sk8-lab/exp2 实测确定）
# ---------------------------------------------------------------------------


def _tmp_dir(media: SkateClipMedia) -> str:
    """临时目录含 generation，避免新旧 Worker 互相清理。"""
    return f"tmp/{media.media_key}/{media.claim_generation}"


def _build_main_args(source_abs: str, tmp_key: str) -> list[str]:
    cfg = settings.SKATE_CLIP_ENCODE_MAIN
    scale = (
        f"scale=w={cfg['max_dimension']}:h={cfg['max_dimension']}:"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    return [
        "-i", source_abs,
        "-vf", scale,
        "-c:v", "libvpx-vp9",
        "-crf", str(cfg["crf"]),
        "-b:v", "0",
        "-deadline", "good",
        "-cpu-used", str(cfg["cpu_used"]),
        "-row-mt", "1",
        "-pix_fmt", "yuv420p",
        "-c:a", "libopus",
        "-b:a", cfg["audio_bitrate"],
        tmp_key,
    ]


def _build_preview_args(source_abs: str, tmp_key: str, duration_ms: int | None) -> list[str]:
    cfg = settings.SKATE_CLIP_ENCODE_PREVIEW
    seconds = float(cfg["seconds"])
    if duration_ms:
        source_s = duration_ms / 1000.0
        start = max(0.0, (source_s - seconds) / 2.0)
        take = min(seconds, source_s)
    else:
        start, take = 0.0, seconds
    red_black = (
        "colorchannelmixer=rr=1.0:gg=0.0:bb=0.0:ra=1:ga=0:ba=0,"
        "eq=contrast=1.5:brightness=-0.03"
    )
    return [
        "-ss", f"{start:.2f}",
        "-i", source_abs,
        "-t", f"{take:.2f}",
        "-an",
        "-vf", f"{red_black},scale=-2:{cfg['height']},fps={cfg['fps']}",
        "-c:v", "libvpx-vp9",
        "-crf", str(cfg["crf"]),
        "-b:v", "0",
        "-deadline", "realtime",
        "-cpu-used", "8",
        "-row-mt", "1",
        "-pix_fmt", "yuv420p",
        tmp_key,
    ]


def _build_poster_args(source_abs: str, tmp_key: str, duration_ms: int | None) -> list[str]:
    cfg = settings.SKATE_CLIP_ENCODE_POSTER
    at = float(cfg["at_seconds"])
    if duration_ms and duration_ms / 1000.0 <= at:
        at = 0.0
    red_black = (
        "colorchannelmixer=rr=1.0:gg=0.0:bb=0.0:ra=1:ga=0:ba=0,"
        "eq=contrast=1.5:brightness=-0.03"
    )
    return [
        "-ss", f"{at:.2f}",
        "-i", source_abs,
        "-frames:v", "1",
        "-vf", f"{red_black},scale={cfg['width']}:-2",
        "-c:v", "libwebp",
        "-quality", str(cfg["quality"]),
        "-an",
        tmp_key,
    ]


# ---------------------------------------------------------------------------
# 临时文件清理
# ---------------------------------------------------------------------------


def _cleanup_tmp(storage, media: SkateClipMedia) -> None:
    tmp_key = _tmp_dir(media)
    parent_key = f"tmp/{media.media_key}"
    try:
        if storage.exists(tmp_key):
            for name in storage.listdir(tmp_key)[1]:
                storage.delete(f"{tmp_key}/{name}")
            storage.delete(tmp_key)
        # 清理空的父目录（generation 子目录已删）
        if storage.exists(parent_key):
            dirs, files = storage.listdir(parent_key)
            if not dirs and not files:
                storage.delete(parent_key)
    except OSError:
        pass


def _cleanup_old_ready(storage, media: SkateClipMedia) -> None:
    """清理上一轮 ready 的旧派生资源（仅在确认新 ready 已落库后调用）。"""
    for key in (
        f"delivery/{media.media_key}/main.webm",
        f"preview/{media.media_key}/preview.webm",
        f"poster/{media.media_key}.webp",
    ):
        try:
            if storage.exists(key):
                storage.delete(key)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 派生校验（§10.8）
# ---------------------------------------------------------------------------


def _validate_derived(delivery, media, main_tmp, preview_tmp, poster_tmp) -> str | None:
    """校验三个产物；返回 None 表示通过，否则返回错误详情。"""
    # main: 可解码 + 尺寸有效 + codec 是 vp9 + 时长漂移有界
    main_result = probe_video_file(delivery.path(main_tmp))
    if not main_result.ok or not main_result.width or not main_result.height:
        return f"main: {main_result.error_code or 'missing dimensions'}"
    if main_result.video_codec not in ("vp9", "vp09"):
        return f"main: unexpected codec {main_result.video_codec}"
    if media.duration_ms and main_result.duration_ms:
        drift = abs(main_result.duration_ms - media.duration_ms)
        if drift > max(1000, media.duration_ms // 10):
            return f"main: duration drift {main_result.duration_ms}ms vs {media.duration_ms}ms"

    # preview: 可解码 + 尺寸有效 + 无音轨 + 时长有界
    preview_result = probe_video_file(delivery.path(preview_tmp))
    if not preview_result.ok or not preview_result.width or not preview_result.height:
        return f"preview: {preview_result.error_code or 'missing dimensions'}"
    if preview_result.has_audio:
        return "preview: unexpected audio track"
    if preview_result.duration_ms and preview_result.duration_ms > settings.SKATE_CLIP_MAX_DURATION_MS:
        return f"preview: duration {preview_result.duration_ms}ms exceeds limit"

    # poster: 非空 + 可读取 WebP + 尺寸有效
    if not delivery.exists(poster_tmp) or delivery.size(poster_tmp) <= 0:
        return "poster: empty output"
    poster_err = _validate_image(delivery.path(poster_tmp))
    if poster_err:
        return f"poster: {poster_err}"

    return None


def _validate_image(path: str) -> str | None:
    """验证 WebP 图片可读取且有有效尺寸（ffprobe 对图片不返回 duration，
    不能复用 probe_video_file）。"""
    import json
    import subprocess as sp

    try:
        proc = sp.run(
            [
                settings.SKATE_CLIP_FFPROBE_PATH,
                "-v", "error",
                "-print_format", "json",
                "-show_streams",
                str(path),
            ],
            capture_output=True, text=True, timeout=settings.SKATE_CLIP_FFPROBE_TIMEOUT,
            check=False, encoding="utf-8", errors="replace",
        )
    except sp.TimeoutExpired:
        return "probe timeout"
    except OSError:
        return "ffprobe not available"
    if proc.returncode != 0:
        return f"ffprobe failed: {_bounded(proc.stderr)}"
    try:
        payload = json.loads(proc.stdout or "")
    except json.JSONDecodeError:
        return "non-JSON output"
    streams = payload.get("streams") or []
    for s in streams:
        try:
            w, h = int(s["width"]), int(s["height"])
            if w > 0 and h > 0:
                return None  # 有效图片
        except (KeyError, TypeError, ValueError):
            continue
    return "no valid image stream"


# ---------------------------------------------------------------------------
# 主处理流程
# ---------------------------------------------------------------------------


def _encode_all(delivery, source_abs, tmp_key, duration_ms) -> str | None:
    """编码三个产物到 tmp 目录。返回 None 表示成功，否则返回错误码。"""
    main_tmp = f"{tmp_key}/main.webm"
    preview_tmp = f"{tmp_key}/preview.webm"
    poster_tmp = f"{tmp_key}/poster.webp"

    try:
        proc = _run_ffmpeg(_build_main_args(source_abs, delivery.path(main_tmp)))
        if proc.returncode != 0:
            return WorkerError.ENCODE_MAIN_FAILED
        proc = _run_ffmpeg(
            _build_preview_args(source_abs, delivery.path(preview_tmp), duration_ms)
        )
        if proc.returncode != 0:
            return WorkerError.ENCODE_PREVIEW_FAILED
        proc = _run_ffmpeg(
            _build_poster_args(source_abs, delivery.path(poster_tmp), duration_ms)
        )
        if proc.returncode != 0:
            return WorkerError.ENCODE_POSTER_FAILED
    except subprocess.TimeoutExpired:
        return WorkerError.FFMPEG_TIMEOUT
    except OSError:
        return WorkerError.FFMPEG_NOT_FOUND
    return None


def _publish_to_final(delivery, media, tmp_key) -> str | None:
    """把校验通过的 tmp 文件原子切换到正式 key。返回 None 表示成功。"""
    main_tmp = f"{tmp_key}/main.webm"
    preview_tmp = f"{tmp_key}/preview.webm"
    poster_tmp = f"{tmp_key}/poster.webp"

    try:
        main_final = f"delivery/{media.media_key}/main.webm"
        preview_final = f"preview/{media.media_key}/preview.webm"
        poster_final = f"poster/{media.media_key}.webp"

        for final_key in (main_final, preview_final, poster_final):
            os.makedirs(os.path.dirname(delivery.path(final_key)), exist_ok=True)

        os.replace(delivery.path(main_tmp), delivery.path(main_final))
        os.replace(delivery.path(preview_tmp), delivery.path(preview_final))
        os.replace(delivery.path(poster_tmp), delivery.path(poster_final))
    except OSError:
        return WorkerError.PROMOTE_FAILED
    return None


def process_media(media: SkateClipMedia) -> bool:
    """处理单条已领取的媒体：派生 → 校验 → 原子发布。返回是否 ready。

    前提：调用者已通过 claim 原子领取（media.state=processing，
    media.claim_generation/token 已设值）。

    竞态安全：最终状态写回使用条件 UPDATE 匹配 (pk, processing,
    generation, token)；若上传替换已递增 generation，条件不匹配，
    本次输出被丢弃，stale 标记写入 error_code 但不改状态。
    """
    delivery = skate_delivery_storage()
    from boards.models import skate_source_storage

    source_storage = skate_source_storage()
    generation = media.claim_generation
    token = media.claim_token

    # 快速失败：源文件不存在
    if not media.source_file or not source_storage.exists(media.source_file.name):
        SkateClipMedia.objects.fail(
            media,
            generation=generation,
            token=token,
            error_code=WorkerError.SOURCE_MISSING,
            error_detail="Private source file not found.",
        )
        return False

    source_abs = source_storage.path(media.source_file.name)
    tmp_key = _tmp_dir(media)

    try:
        _cleanup_tmp(delivery, media)
        os.makedirs(delivery.path(tmp_key), exist_ok=True)

        # 1) 编码三个产物
        encode_err = _encode_all(delivery, source_abs, tmp_key, media.duration_ms)
        if encode_err is not None:
            detail = _encode_detail(delivery, tmp_key)
            SkateClipMedia.objects.fail(
                media,
                generation=generation,
                token=token,
                error_code=encode_err,
                error_detail=detail,
            )
            return False

        # 2) 校验三个产物
        main_tmp = f"{tmp_key}/main.webm"
        preview_tmp = f"{tmp_key}/preview.webm"
        poster_tmp = f"{tmp_key}/poster.webp"
        validation_err = _validate_derived(delivery, media, main_tmp, preview_tmp, poster_tmp)
        if validation_err is not None:
            SkateClipMedia.objects.fail(
                media,
                generation=generation,
                token=token,
                error_code=WorkerError.DERIVED_INVALID,
                error_detail=validation_err,
            )
            return False

        # 3) 原子切换到正式 key
        publish_err = _publish_to_final(delivery, media, tmp_key)
        if publish_err is not None:
            SkateClipMedia.objects.fail(
                media,
                generation=generation,
                token=token,
                error_code=publish_err,
                error_detail="os.replace failed during promotion.",
            )
            return False

        # 4) 条件 UPDATE 切换数据库状态为 ready
        main_key = f"delivery/{media.media_key}/main.webm"
        preview_key = f"preview/{media.media_key}/preview.webm"
        poster_key = f"poster/{media.media_key}.webp"

        success = SkateClipMedia.objects.finish(
            media,
            generation=generation,
            token=token,
            main_key=main_key,
            preview_key=preview_key,
            poster_key=poster_key,
        )
        if not success:
            # Stale claim：上传替换已使旧 generation 失效。
            # 新文件已落盘但数据库不会被切换（新 generation 的 Worker
            # 会重新处理）。不做清理——新 Worker 的 _cleanup_tmp 会处理。
            media.error_code = WorkerError.STALE_CLAIM
            return False

        media.state = SkateClipMediaState.READY
        media.claimed_at = None
        media.error_code = ""
        media.error_detail = ""
        media.processed_at = timezone.now()
        media.main_file = main_key
        media.preview_file = preview_key
        media.poster_file = poster_key
        return True

    except subprocess.TimeoutExpired:
        SkateClipMedia.objects.fail(
            media,
            generation=generation,
            token=token,
            error_code=WorkerError.FFMPEG_TIMEOUT,
            error_detail="FFmpeg timed out.",
        )
        return False
    except OSError as exc:
        SkateClipMedia.objects.fail(
            media,
            generation=generation,
            token=token,
            error_code=WorkerError.FFMPEG_NOT_FOUND,
            error_detail=_bounded(str(exc)),
        )
        return False
    except Exception as exc:
        SkateClipMedia.objects.fail(
            media,
            generation=generation,
            token=token,
            error_code=WorkerError.WORKER_UNEXPECTED,
            error_detail=_bounded(str(exc)),
        )
        return False
    finally:
        _cleanup_tmp(delivery, media)


def _encode_detail(delivery, tmp_key: str) -> str:
    """提取编码失败的诊断摘要（有界）。"""
    parts = []
    for name in ("main.webm", "preview.webm", "poster.webp"):
        tmp = f"{tmp_key}/{name}"
        if delivery.exists(tmp):
            parts.append(f"{name}: {delivery.size(tmp)} bytes")
    return "; ".join(parts) if parts else "no partial output"
