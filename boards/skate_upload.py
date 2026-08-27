"""Skate clip source ingestion shared by create/edit and legacy replace views."""

from dataclasses import dataclass

from django.db import transaction

from boards.models import (
    SkateClipMedia,
    SkateClipMediaState,
    skate_source_storage,
)
from boards.skate_media import (
    CLIP_PROBE_ERROR_MESSAGES,
    probe_video_file,
    sha256_file,
)


_UPLOAD_ERROR_MESSAGES = {
    **CLIP_PROBE_ERROR_MESSAGES,
    "source_missing": "该 Clip 没有可重新处理的私有原片，请先选择视频文件。",
}


@dataclass(frozen=True)
class SkateUploadRejected(Exception):
    code: str

    @property
    def public_message(self):
        return _UPLOAD_ERROR_MESSAGES.get(
            self.code, "上传校验失败，请稍后重试。"
        )


def ingest_skate_source(*, clip, uploaded, uploaded_by):
    """Persist, probe and attach one source file; clean both failure paths."""
    storage = skate_source_storage()
    saved_name = None
    try:
        saved_name = storage.save(
            SkateClipMedia.build_source_key(uploaded.name), uploaded
        )
        probe = probe_video_file(storage.path(saved_name))
        if not probe.ok:
            raise SkateUploadRejected(probe.error_code)
        source_size = storage.size(saved_name)
        digest = sha256_file(storage.path(saved_name))
    except SkateUploadRejected:
        if saved_name:
            try:
                storage.delete(saved_name)
            except OSError:
                pass
        raise
    except OSError as exc:
        if saved_name:
            try:
                storage.delete(saved_name)
            except OSError:
                pass
        raise SkateUploadRejected("probe_failed") from exc

    old_source = ""
    try:
        with transaction.atomic():
            media, created = SkateClipMedia.objects.select_for_update().get_or_create(
                clip=clip,
                defaults={"uploaded_by": uploaded_by},
            )
            old_source = media.source_file.name if media.source_file else ""
            if not created and media.state == SkateClipMediaState.PROCESSING:
                SkateClipMedia.objects.invalidate_claim(media)
            media.uploaded_by = uploaded_by
            media.source_file = saved_name
            media.source_size = source_size
            media.source_sha256 = digest
            media.state = SkateClipMediaState.UPLOADED
            media.error_code = ""
            media.error_detail = ""
            media.processed_at = None
            media.apply_probe(
                duration_ms=probe.duration_ms,
                width=probe.width,
                height=probe.height,
                frame_rate=probe.frame_rate,
            )
            media.save()
    except Exception:
        try:
            storage.delete(saved_name)
        except OSError:
            pass
        raise

    if old_source and old_source != saved_name:
        try:
            storage.delete(old_source)
        except OSError:
            pass
    return media


def requeue_existing_skate_source(*, clip):
    """Move an existing private source back to the worker queue.

    The row lock and claim invalidation keep an older in-flight worker from
    publishing over this retry. File validation remains the worker's
    responsibility, so the HTTP request performs no FFmpeg or file IO.
    """
    with transaction.atomic():
        media = (
            SkateClipMedia.objects.select_for_update()
            .filter(clip=clip)
            .first()
        )
        if media is None or not media.source_file:
            raise SkateUploadRejected("source_missing")
        if media.state == SkateClipMediaState.PROCESSING:
            SkateClipMedia.objects.invalidate_claim(media)
        media.state = SkateClipMediaState.UPLOADED
        media.claimed_at = None
        media.error_code = ""
        media.error_detail = ""
        media.processed_at = None
        media.save(
            update_fields=[
                "state",
                "claimed_at",
                "claim_generation",
                "claim_token",
                "error_code",
                "error_detail",
                "processed_at",
                "updated_at",
            ]
        )
    return media
