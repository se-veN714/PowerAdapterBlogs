"""SK8 S2 测试：处理 Worker（原子领取、claim 所有权、派生、校验、原子发布、卡死复位）。

纯逻辑部分不依赖 FFmpeg；集成部分在工具可用时走完整
"私有原片 → main/preview/poster → 校验 → ready" 链路。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from boards.models import (
    Board,
    SkateClip,
    SkateClipMedia,
    SkateClipMediaState,
    SkateHomie,
    skate_delivery_storage,
    skate_source_storage,
)
from boards.skate_worker import (
    WorkerError,
    _build_main_args,
    _build_poster_args,
    _build_preview_args,
    claim_media_by_pk,
    claim_next_media,
    process_media,
    reset_stuck_media,
)


def _find_binary(env_key: str, name: str) -> str | None:
    candidate = os.environ.get(env_key, "")
    if candidate and Path(candidate).is_file():
        return candidate
    return shutil.which(name)


FFMPEG = _find_binary("SKATE_FFMPEG", settings.SKATE_CLIP_FFMPEG_PATH
                      if settings.SKATE_CLIP_FFMPEG_PATH != "ffmpeg" else "ffmpeg")
FFPROBE = _find_binary("SKATE_FFPROBE", settings.SKATE_CLIP_FFPROBE_PATH
                       if settings.SKATE_CLIP_FFPROBE_PATH != "ffprobe" else "ffprobe")
HAVE_FFMPEG_TOOLS = bool(FFMPEG and FFPROBE)


def make_media(**overrides) -> SkateClipMedia:
    board, _ = Board.objects.get_or_create(slug="skateboard", name="Skateboard")
    homie = SkateHomie.objects.create(
        board=board,
        node_index=SkateHomie.objects.count() + 1,
        name="Tester",
        joined_at="2026-08-01",
    )
    clip = SkateClip.objects.create(homie=homie, order=0, title="Ollie")
    return SkateClipMedia.objects.create(clip=clip, **overrides)


# ---------------------------------------------------------------------------
# 不依赖 FFmpeg 的纯逻辑测试
# ---------------------------------------------------------------------------


class ClaimAndResetTests(TestCase):
    def test_claim_moves_uploaded_to_processing(self):
        media = make_media(state=SkateClipMediaState.UPLOADED)

        claimed = claim_next_media()

        self.assertEqual(claimed.pk, media.pk)
        media.refresh_from_db()
        self.assertEqual(media.state, SkateClipMediaState.PROCESSING)
        self.assertIsNotNone(media.claimed_at)
        self.assertGreater(media.claim_generation, 0)
        self.assertIsNotNone(media.claim_token)

    def test_claim_returns_none_when_empty(self):
        self.assertIsNone(claim_next_media())

    def test_claim_skips_non_uploaded_states(self):
        make_media(state=SkateClipMediaState.READY)
        make_media(state=SkateClipMediaState.FAILED)
        make_media(state=SkateClipMediaState.PROCESSING)

        self.assertIsNone(claim_next_media())

    def test_claim_by_pk_atomically_claims(self):
        media = make_media(state=SkateClipMediaState.UPLOADED)

        claimed = claim_media_by_pk(media.pk)

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.pk, media.pk)
        media.refresh_from_db()
        self.assertEqual(media.state, SkateClipMediaState.PROCESSING)

    def test_claim_by_pk_returns_none_for_wrong_state(self):
        media = make_media(state=SkateClipMediaState.READY)

        self.assertIsNone(claim_media_by_pk(media.pk))

    def test_claim_by_pk_returns_none_for_missing(self):
        self.assertIsNone(claim_media_by_pk(999_999))

    def test_reset_stuck_only_touches_expired_processing(self):
        stuck = make_media(state=SkateClipMediaState.PROCESSING)
        SkateClipMedia.objects.filter(pk=stuck.pk).update(
            claimed_at=timezone.now() - timedelta(seconds=settings.SKATE_CLIP_STUCK_PROCESSING_SECONDS + 60)
        )
        fresh = make_media(state=SkateClipMediaState.PROCESSING)
        SkateClipMedia.objects.filter(pk=fresh.pk).update(claimed_at=timezone.now())

        reset = reset_stuck_media()

        self.assertEqual(reset, 1)
        stuck.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(stuck.state, SkateClipMediaState.UPLOADED)
        self.assertIsNone(stuck.claimed_at)
        self.assertEqual(fresh.state, SkateClipMediaState.PROCESSING)


class ClaimOwnershipTests(TestCase):
    """§10.1 stale worker 条件更新 + §10.2 上传替换使旧 claim 失效。"""

    def test_finish_requires_matching_generation_and_token(self):
        media = make_media(state=SkateClipMediaState.UPLOADED)
        claimed = claim_next_media()
        self.assertIsNotNone(claimed)

        # 错误 generation → 写回失败
        ok = SkateClipMedia.objects.finish(
            media,
            generation=claimed.claim_generation + 999,
            token=claimed.claim_token,
            main_key="delivery/x/main.webm",
        )
        self.assertFalse(ok)

        # 错误 token → 写回失败
        import uuid
        ok = SkateClipMedia.objects.finish(
            media,
            generation=claimed.claim_generation,
            token=uuid.uuid4(),
            main_key="delivery/x/main.webm",
        )
        self.assertFalse(ok)

        # 正确 generation + token → 写回成功
        ok = SkateClipMedia.objects.finish(
            media,
            generation=claimed.claim_generation,
            token=claimed.claim_token,
            main_key="delivery/x/main.webm",
            preview_key="preview/x/preview.webm",
            poster_key="poster/x.webp",
        )
        self.assertTrue(ok)
        media.refresh_from_db()
        self.assertEqual(media.state, SkateClipMediaState.READY)

    def test_fail_requires_matching_generation_and_token(self):
        media = make_media(state=SkateClipMediaState.UPLOADED)
        claimed = claim_next_media()

        ok = SkateClipMedia.objects.fail(
            media,
            generation=claimed.claim_generation + 1,
            token=claimed.claim_token,
            error_code=WorkerError.SOURCE_MISSING,
            error_detail="x",
        )
        self.assertFalse(ok)
        media.refresh_from_db()
        self.assertEqual(media.state, SkateClipMediaState.PROCESSING)  # 未被改

    def test_invalidate_claim_makes_finish_fail(self):
        """上传替换使旧 claim 失效——递增 generation。"""
        media = make_media(state=SkateClipMediaState.UPLOADED)
        claimed = claim_next_media()
        old_generation = claimed.claim_generation
        old_token = claimed.claim_token

        # 模拟上传替换调用 invalidate_claim
        SkateClipMedia.objects.invalidate_claim(media)
        media.save(update_fields=["claim_generation", "claim_token", "updated_at"])

        # 旧 Worker 试图用旧 generation/token finish → 失败
        ok = SkateClipMedia.objects.finish(
            media,
            generation=old_generation,
            token=old_token,
            main_key="delivery/x/main.webm",
        )
        self.assertFalse(ok)
        media.refresh_from_db()
        self.assertNotEqual(media.state, SkateClipMediaState.READY)


class RecipeArgsTests(SimpleTestCase):
    def test_main_args_shape(self):
        args = _build_main_args("src.mp4", "out.webm")
        joined = " ".join(args)
        self.assertIn("-c:v libvpx-vp9", joined)
        self.assertIn("-deadline good", joined)
        self.assertIn("-cpu-used 4", joined)
        self.assertIn("-c:a libopus", joined)
        self.assertIn("force_original_aspect_ratio=decrease", joined)

    def test_preview_args_midpoint_and_redblack(self):
        args = _build_preview_args("src.mp4", "out.webm", duration_ms=8_000)
        joined = " ".join(args)
        self.assertIn("-ss 2.50", joined)
        self.assertIn("-t 3.00", joined)
        self.assertIn("-an", joined)
        self.assertIn("colorchannelmixer", joined)
        self.assertIn("scale=-2:480", joined)
        self.assertIn("fps=15", joined)

    def test_preview_short_source_takes_whole_clip(self):
        args = _build_preview_args("src.mp4", "out.webm", duration_ms=2_000)
        joined = " ".join(args)
        self.assertIn("-ss 0.00", joined)
        self.assertIn("-t 2.00", joined)

    def test_poster_args_first_frame_for_short_source(self):
        args = _build_poster_args("src.mp4", "out.webp", duration_ms=800)
        joined = " ".join(args)
        self.assertIn("-ss 0.00", joined)
        self.assertIn("-frames:v 1", joined)
        self.assertIn("libwebp", joined)


class ManagementCommandNoFfmpegTests(TestCase):
    """不依赖 FFmpeg 的命令测试（--media-id 报错、dry-run 报告）。"""

    def setUp(self):
        self.media = make_media(state=SkateClipMediaState.UPLOADED)

    def test_dry_run_reports_pending(self):
        from io import StringIO

        out = StringIO()
        call_command("process_skate_clips", dry_run=True, stdout=out)
        self.assertIn("pending=1", out.getvalue())

    def test_media_id_not_found_raises_command_error(self):
        from io import StringIO

        with self.assertRaises(CommandError):
            call_command("process_skate_clips", media_id=999_999, stdout=StringIO())

    def test_media_id_wrong_state_raises_command_error(self):
        from io import StringIO

        self.media.state = SkateClipMediaState.READY
        self.media.save()
        with self.assertRaises(CommandError):
            call_command("process_skate_clips", media_id=self.media.pk, stdout=StringIO())


# ---------------------------------------------------------------------------
# 依赖 FFmpeg 的集成测试
# ---------------------------------------------------------------------------


@skipUnless(HAVE_FFMPEG_TOOLS, "FFmpeg/FFprobe not available on PATH or SKATE_* env")
class ProcessMediaIntegrationTests(TestCase):
    """完整派生链路（真实 FFmpeg，小分辨率样片控制耗时）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lab = tempfile.TemporaryDirectory()
        cls.source_path = Path(cls.lab.name) / "source.mp4"
        subprocess.run(
            [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi",
                "-i", "testsrc2=size=320x568:rate=24:duration=4",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
                "-shortest", str(cls.source_path),
            ],
            check=True, capture_output=True, timeout=120,
        )

    @classmethod
    def tearDownClass(cls):
        cls.lab.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.src_tmp = tempfile.TemporaryDirectory()
        self.dst_tmp = tempfile.TemporaryDirectory()
        self.ctx = override_settings(
            SKATE_CLIP_SOURCE_ROOT=Path(self.src_tmp.name),
            SKATE_CLIP_DELIVERY_ROOT=Path(self.dst_tmp.name),
            SKATE_CLIP_FFPROBE_PATH=FFPROBE,
            SKATE_CLIP_FFMPEG_PATH=FFMPEG,
            SKATE_CLIP_ENCODE_MAIN={"cpu_used": 8, "crf": 40, "audio_bitrate": "64k", "max_dimension": 640},
        )
        self.ctx.enable()
        self.addCleanup(self.ctx.disable)
        self.addCleanup(self.src_tmp.cleanup)
        self.addCleanup(self.dst_tmp.cleanup)

        storage = skate_source_storage()
        saved = storage.save("aabbccdd" * 4 + ".mp4", open(self.source_path, "rb"))
        self.media = make_media(
            state=SkateClipMediaState.UPLOADED,
            source_file=saved,
            duration_ms=4_000,
            width=320,
            height=568,
            orientation="portrait",
            frame_rate="24/1",
        )

    def _claim_and_process(self):
        claimed = claim_next_media()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.pk, self.media.pk)
        return process_media(claimed)

    def test_full_pipeline_marks_ready_with_derived_assets(self):
        ok = self._claim_and_process()

        self.assertTrue(ok)
        self.media.refresh_from_db()
        self.assertEqual(self.media.state, SkateClipMediaState.READY)
        self.assertIsNotNone(self.media.processed_at)
        self.assertEqual(self.media.error_code, "")

        delivery = skate_delivery_storage()
        main_key = self.media.main_file.name
        preview_key = self.media.preview_file.name
        poster_key = self.media.poster_file.name
        version = f"{self.media.claim_generation}-{self.media.claim_token.hex}"
        self.assertIn(version, main_key)
        self.assertIn(version, preview_key)
        self.assertIn(version, poster_key)
        for key in (main_key, preview_key, poster_key):
            self.assertTrue(delivery.exists(key), key)
            self.assertGreater(delivery.size(key), 0, key)
        self.assertEqual(self.media.main_file, main_key)
        self.assertEqual(self.media.preview_file, preview_key)
        self.assertEqual(self.media.poster_file, poster_key)

        # main 保留音轨（Opus）；preview 无音轨且更短。
        probe_main = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json", "-show_streams",
             delivery.path(main_key)],
            capture_output=True, text=True, timeout=15, check=True,
        )
        self.assertIn("opus", probe_main.stdout)
        probe_preview = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json", "-show_streams",
             delivery.path(preview_key)],
            capture_output=True, text=True, timeout=15, check=True,
        )
        self.assertNotIn('"codec_type": "audio"', probe_preview.stdout)

        # tmp/ 不留残留（generation 子目录也应清理）
        self.assertFalse(delivery.exists(f"tmp/{self.media.media_key}"))

    def test_ready_media_not_claimed_again(self):
        self._claim_and_process()
        self.assertIsNone(claim_next_media())

    def test_missing_source_fails_with_bounded_error(self):
        storage = skate_source_storage()
        storage.delete(self.media.source_file.name)

        ok = self._claim_and_process()

        self.assertFalse(ok)
        self.media.refresh_from_db()
        self.assertEqual(self.media.state, SkateClipMediaState.FAILED)
        self.assertEqual(self.media.error_code, WorkerError.SOURCE_MISSING)
        self.assertIsNone(self.media.claimed_at)

    def test_stale_worker_output_discarded_on_replacement(self):
        """§10.2 上传替换使旧 Worker claim 失效：finish 条件不匹配。"""
        claimed = claim_next_media()

        # 模拟上传替换使旧 claim 失效
        self.media.refresh_from_db()
        SkateClipMedia.objects.invalidate_claim(self.media)
        SkateClipMedia.objects.filter(pk=self.media.pk).update(
            claim_generation=self.media.claim_generation,
            claim_token=self.media.claim_token,
            state=SkateClipMediaState.UPLOADED,
        )

        # 旧 Worker 试图用旧 generation 处理 → finish 失败
        ok = process_media(claimed)
        self.assertFalse(ok)
        self.media.refresh_from_db()
        # 状态不应被旧 Worker 改为 ready
        self.assertNotEqual(self.media.state, SkateClipMediaState.READY)
        delivery = skate_delivery_storage()
        stale_version = f"{claimed.claim_generation}-{claimed.claim_token.hex}"
        self.assertFalse(delivery.exists(f"delivery/{claimed.media_key}/{stale_version}/main.webm"))

    def test_partial_promotion_never_replaces_previous_ready_assets(self):
        """第二个 os.replace 失败时，数据库引用与旧文件内容保持一致。"""
        delivery = skate_delivery_storage()
        old_keys = (
            f"delivery/{self.media.media_key}/old/main.webm",
            f"preview/{self.media.media_key}/old/preview.webm",
            f"poster/{self.media.media_key}/old/poster.webp",
        )
        from django.core.files.base import ContentFile

        for key in old_keys:
            delivery.save(key, ContentFile(b"old"))
        SkateClipMedia.objects.filter(pk=self.media.pk).update(
            main_file=old_keys[0], preview_file=old_keys[1], poster_file=old_keys[2]
        )
        self.media.refresh_from_db()
        claimed = claim_next_media()
        real_replace = os.replace
        calls = 0

        def fail_second(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated partial promotion")
            return real_replace(source, target)

        with mock.patch("boards.skate_worker.os.replace", side_effect=fail_second):
            self.assertFalse(process_media(claimed))

        self.media.refresh_from_db()
        self.assertEqual(self.media.main_file.name, old_keys[0])
        self.assertEqual(self.media.preview_file.name, old_keys[1])
        self.assertEqual(self.media.poster_file.name, old_keys[2])
        for key in old_keys:
            self.assertEqual(delivery.open(key).read(), b"old")

    def test_management_command_processes_queue(self):
        from io import StringIO

        out = StringIO()
        call_command("process_skate_clips", stdout=out)
        self.media.refresh_from_db()
        self.assertEqual(self.media.state, SkateClipMediaState.READY)
        self.assertIn("ready=1", out.getvalue())

    def test_management_command_media_id(self):
        from io import StringIO

        out = StringIO()
        call_command("process_skate_clips", media_id=self.media.pk, stdout=out)
        self.media.refresh_from_db()
        self.assertEqual(self.media.state, SkateClipMediaState.READY)
        self.assertIn("ready=1", out.getvalue())
