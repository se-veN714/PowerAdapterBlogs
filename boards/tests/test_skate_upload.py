"""SK8 S1 测试：上传三层校验（浏览器预检外的服务端两层）。

纯逻辑部分不依赖 FFprobe 可执行文件；集成部分在 FFmpeg/FFprobe
可用时执行真实"上传 → 写私有存储 → 权威探测 → 落库"链路，
覆盖伪扩展名 / 损坏 / 超 20 秒 / 超大小 / 未授权 / 替换清理。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from boards.models import Board, SkateClip, SkateClipMedia, SkateClipMediaState, SkateHomie
from boards.skate_media import (
    ClipProbeError,
    parse_probe_payload,
    probe_video_file,
    sha256_file,
)
from boards.content_forms import SkateClipMediaUploadForm
from boards.skate_upload import SkateUploadRejected, requeue_existing_skate_source


def _find_binary(env_key: str, name: str) -> str | None:
    candidate = os.environ.get(env_key, "")
    if candidate and Path(candidate).is_file():
        return candidate
    return shutil.which(name)


FFMPEG = _find_binary("SKATE_FFMPEG", "ffmpeg")
FFPROBE = _find_binary(
    "SKATE_FFPROBE",
    settings.SKATE_CLIP_FFPROBE_PATH
    if settings.SKATE_CLIP_FFPROBE_PATH != "ffprobe"
    else "ffprobe",
)
HAVE_FFMPEG_TOOLS = bool(FFMPEG and FFPROBE)


def make_clip() -> SkateClip:
    board, _ = Board.objects.get_or_create(slug="skateboard", name="Skateboard")
    homie = SkateHomie.objects.create(
        board=board,
        node_index=SkateHomie.objects.count() + 1,
        name="Tester",
        joined_at="2026-08-01",
    )
    return SkateClip.objects.create(homie=homie, order=0, title="Ollie")


def _payload(**overrides) -> dict:
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "r_frame_rate": "30/1",
                "duration": "8.500000",
            }
        ],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "8.500000"},
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 纯逻辑测试（不依赖 FFmpeg/FFprobe）
# ---------------------------------------------------------------------------


class ParseProbePayloadTests(SimpleTestCase):
    def test_valid_portrait(self):
        result = parse_probe_payload(_payload())
        self.assertTrue(result.ok)
        self.assertEqual(result.duration_ms, 8_500)
        self.assertEqual((result.width, result.height), (1080, 1920))
        self.assertIsNone(result.rotation)
        self.assertFalse(result.has_audio)
        self.assertEqual(result.frame_rate, "30/1")
        self.assertEqual(result.video_codec, "h264")

    def test_rotation_swaps_display_dimensions(self):
        payload = _payload(
            streams=[
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "30/1",
                    "side_data_list": [
                        {"side_data_type": "Display Matrix", "rotation": 90}
                    ],
                }
            ]
        )
        result = parse_probe_payload(payload)
        self.assertTrue(result.ok)
        self.assertEqual((result.coded_width, result.coded_height), (1280, 720))
        self.assertEqual((result.width, result.height), (720, 1280))
        self.assertEqual(result.rotation, 90)

    def test_no_video_stream(self):
        result = parse_probe_payload({"streams": [], "format": {}})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ClipProbeError.NO_VIDEO_STREAM)

    def test_duration_missing(self):
        payload = _payload(format={"format_name": "mov,mp4"})
        for stream in payload["streams"]:
            stream.pop("duration")
        result = parse_probe_payload(payload)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ClipProbeError.DURATION_MISSING)

    def test_duration_exceeded_at_boundary(self):
        with override_settings(SKATE_CLIP_MAX_DURATION_MS=20_000):
            at_limit = parse_probe_payload(_payload(format={"duration": "20.000"}))
            over_limit = parse_probe_payload(_payload(format={"duration": "20.001"}))
        self.assertTrue(at_limit.ok)
        self.assertEqual(at_limit.duration_ms, 20_000)
        self.assertFalse(over_limit.ok)
        self.assertEqual(over_limit.error_code, ClipProbeError.DURATION_EXCEEDED)

    def test_degenerate_frame_rate_normalized(self):
        payload = _payload()
        payload["streams"][0]["r_frame_rate"] = "0/0"
        result = parse_probe_payload(payload)
        self.assertTrue(result.ok)
        self.assertEqual(result.frame_rate, "")

    def test_audio_stream_detected(self):
        payload = _payload(
            streams=_payload()["streams"]
            + [{"codec_type": "audio", "codec_name": "aac"}]
        )
        result = parse_probe_payload(payload)
        self.assertTrue(result.has_audio)

    def test_nan_duration_rejected(self):
        payload = _payload(format={"duration": "nan"})
        result = parse_probe_payload(payload)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ClipProbeError.DURATION_MISSING)

    def test_inf_duration_rejected(self):
        payload = _payload(format={"duration": "inf"})
        result = parse_probe_payload(payload)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ClipProbeError.DURATION_MISSING)

    def test_zero_dimensions_rejected(self):
        payload = _payload(
            streams=[{
                "codec_type": "video",
                "codec_name": "h264",
                "width": 0,
                "height": 0,
                "r_frame_rate": "30/1",
                "duration": "8.5",
            }],
            format={"format_name": "mov,mp4", "duration": "8.5"},
        )
        result = parse_probe_payload(payload)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ClipProbeError.NO_VIDEO_STREAM)


class BuildSourceKeyTests(SimpleTestCase):
    def test_key_is_server_uuid(self):
        key = SkateClipMedia.build_source_key("client-name.mp4")
        self.assertRegex(key, r"^[0-9a-f]{32}\.mp4$")
        self.assertNotEqual(key, SkateClipMedia.build_source_key("client-name.mp4"))


class UploadFormTests(SimpleTestCase):
    def test_size_limit_fast_fail(self):
        with override_settings(SKATE_CLIP_MAX_UPLOAD_BYTES=1024):
            form = SkateClipMediaUploadForm(
                files={"source": SimpleUploadedFile("big.mp4", b"x" * 2048)}
            )
            self.assertFalse(form.is_valid())
            self.assertIn("大小上限", form.errors["source"][0])


class ProbeTimeoutTests(SimpleTestCase):
    def test_probe_timeout_returns_bounded_error(self):
        from unittest import mock
        import subprocess as sp

        with override_settings(SKATE_CLIP_FFPROBE_TIMEOUT=0.0001):
            with mock.patch("boards.skate_media.run_ffprobe") as runner:
                runner.side_effect = sp.TimeoutExpired(cmd="ffprobe", timeout=0.0001)
                result = probe_video_file("/nonexistent/path.mp4")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ClipProbeError.PROBE_TIMEOUT)


# ---------------------------------------------------------------------------
# 不依赖 FFmpeg 的权限/HTTP 测试
# ---------------------------------------------------------------------------


class UploadPermissionTests(TestCase):
    """匿名 302、普通用户 403、Manager 200、未知 Clip 404。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings_ctx = override_settings(SKATE_CLIP_SOURCE_ROOT=Path(self.tmp.name))
        settings_ctx.enable()
        self.addCleanup(settings_ctx.disable)
        self.addCleanup(self.tmp.cleanup)

        self.board = Board.objects.create(slug="skateboard", name="Skateboard")
        homie = SkateHomie.objects.create(
            board=self.board, node_index=1, name="Tester", joined_at="2026-08-01"
        )
        self.clip = SkateClip.objects.create(homie=homie, order=0, title="Ollie")

        self.manager = get_user_model().objects.create_user(
            username="skmanager",
            email="sk@example.com",
            password="pw-123456",
            is_active=True,
        )
        from boards.models import BoardMembership

        BoardMembership.objects.create(
            board=self.board,
            user=self.manager,
            role=BoardMembership.Role.MANAGER,
            is_active=True,
        )
        self.url = f"/boards/manage/skateboard/clips/{self.clip.pk}/media/upload/"

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_plain_user_forbidden(self):
        user = get_user_model().objects.create_user(
            username="plain2",
            email="p2@example.com",
            password="pw-123456",
            is_active=True,
        )
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_manager_can_open_upload_page(self):
        self.client.force_login(self.manager)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UPLOAD MEDIA")
        self.assertContains(response, "data-skate-drop")
        self.assertContains(response, "DROP VIDEO / SELECT FILE")

    def test_existing_media_requires_explicit_replace_confirmation(self):
        SkateClipMedia.objects.create(clip=self.clip, uploaded_by=self.manager)
        self.client.force_login(self.manager)

        with mock.patch("boards.content_views.ingest_skate_source") as ingest:
            response = self.client.post(
                self.url,
                {"source": SimpleUploadedFile("replace.webm", b"video")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "REPLACE MEDIA")
        self.assertContains(response, "系统不会为同一 Clip 追加第二个视频")
        ingest.assert_not_called()

    def test_existing_media_can_be_replaced_after_confirmation(self):
        SkateClipMedia.objects.create(clip=self.clip, uploaded_by=self.manager)
        self.client.force_login(self.manager)

        with mock.patch("boards.content_views.ingest_skate_source") as ingest:
            response = self.client.post(
                self.url,
                {
                    "source": SimpleUploadedFile("replace.webm", b"video"),
                    "confirm_replace": "on",
                },
            )

        self.assertEqual(response.status_code, 302)
        ingest.assert_called_once()

    def test_unknown_clip_404(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            f"/boards/manage/skateboard/clips/{self.clip.pk + 999}/media/upload/"
        )
        self.assertEqual(response.status_code, 404)

    def test_size_limit_rejected_before_probe(self):
        self.client.force_login(self.manager)
        with override_settings(SKATE_CLIP_MAX_UPLOAD_BYTES=1024):
            response = self.client.post(
                self.url,
                {"source": SimpleUploadedFile("ok.mp4", b"x" * 2048)},
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SkateClipMedia.objects.filter(clip=self.clip).exists())


class RequeueExistingSourceTests(TestCase):
    def setUp(self):
        self.clip = make_clip()

    def test_failed_media_with_private_source_returns_to_uploaded(self):
        media = SkateClipMedia.objects.create(
            clip=self.clip,
            source_file="source/existing.webm",
            state=SkateClipMediaState.FAILED,
            error_code="encode_main_failed",
            error_detail="bounded detail",
        )

        requeue_existing_skate_source(clip=self.clip)

        media.refresh_from_db()
        self.assertEqual(media.state, SkateClipMediaState.UPLOADED)
        self.assertEqual(media.error_code, "")
        self.assertEqual(media.error_detail, "")

    def test_processing_media_invalidates_previous_claim(self):
        media = SkateClipMedia.objects.create(
            clip=self.clip,
            source_file="source/existing.webm",
            state=SkateClipMediaState.PROCESSING,
            claim_generation=3,
        )

        requeue_existing_skate_source(clip=self.clip)

        media.refresh_from_db()
        self.assertEqual(media.state, SkateClipMediaState.UPLOADED)
        self.assertEqual(media.claim_generation, 4)

    def test_missing_private_source_is_rejected(self):
        SkateClipMedia.objects.create(clip=self.clip)

        with self.assertRaises(SkateUploadRejected) as raised:
            requeue_existing_skate_source(clip=self.clip)

        self.assertEqual(raised.exception.code, "source_missing")


# ---------------------------------------------------------------------------
# 依赖 FFmpeg 的集成测试
# ---------------------------------------------------------------------------


@skipUnless(HAVE_FFMPEG_TOOLS, "FFmpeg/FFprobe not available on PATH or SKATE_* env")
class SkateClipUploadIntegrationTests(TestCase):
    """真实上传链路：私有存储 + FFprobe 权威裁决 + 状态落库。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lab = tempfile.TemporaryDirectory()
        lab_path = Path(cls.lab.name)
        cls.ok_path = lab_path / "ok.mp4"
        cls.long_path = lab_path / "long.mp4"
        cls.fake_path = lab_path / "fake.mp4"
        subprocess.run(
            [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=24:duration=2",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", str(cls.ok_path),
            ],
            check=True, capture_output=True, timeout=120,
        )
        subprocess.run(
            [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=24:duration=21",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", str(cls.long_path),
            ],
            check=True, capture_output=True, timeout=120,
        )
        cls.fake_path.write_text("not a video at all", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.lab.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings_ctx = override_settings(
            SKATE_CLIP_SOURCE_ROOT=Path(self.tmp.name),
            SKATE_CLIP_FFPROBE_PATH=FFPROBE,
        )
        settings_ctx.enable()
        self.addCleanup(settings_ctx.disable)
        self.addCleanup(self.tmp.cleanup)

        self.board = Board.objects.create(slug="skateboard", name="Skateboard")
        homie = SkateHomie.objects.create(
            board=self.board, node_index=1, name="Tester", joined_at="2026-08-01"
        )
        self.clip = SkateClip.objects.create(homie=homie, order=0, title="Ollie")

        self.manager = get_user_model().objects.create_user(
            username="skmanager",
            email="sk@example.com",
            password="pw-123456",
            is_active=True,
        )
        from boards.models import BoardMembership

        BoardMembership.objects.create(
            board=self.board,
            user=self.manager,
            role=BoardMembership.Role.MANAGER,
            is_active=True,
        )
        self.url = f"/boards/manage/skateboard/clips/{self.clip.pk}/media/upload/"

    def post_file(self, path: Path):
        content = path.read_bytes()
        return self.client.post(
            self.url,
            {"source": SimpleUploadedFile(path.name, content)},
        )

    def test_valid_upload_creates_uploaded_media(self):
        self.client.force_login(self.manager)

        response = self.post_file(self.ok_path)

        self.assertEqual(response.status_code, 302)
        media = SkateClipMedia.objects.get(clip=self.clip)
        self.assertEqual(media.state, SkateClipMediaState.UPLOADED)
        self.assertEqual(media.uploaded_by, self.manager)
        self.assertIsNotNone(media.duration_ms)
        self.assertEqual((media.width, media.height), (320, 568))
        self.assertEqual(media.orientation, "portrait")
        self.assertEqual(media.source_size, self.ok_path.stat().st_size)
        self.assertEqual(media.source_sha256, sha256_file(self.ok_path))
        source_abs = Path(settings.SKATE_CLIP_SOURCE_ROOT) / media.source_file.name
        self.assertTrue(source_abs.is_file())
        self.assertEqual(
            source_abs.read_bytes()[:64], self.ok_path.read_bytes()[:64]
        )

    def test_fake_extension_rejected_and_no_residue(self):
        self.client.force_login(self.manager)

        response = self.post_file(self.fake_path)

        self.assertEqual(response.status_code, 200)  # 表单页回显错误
        self.assertFalse(SkateClipMedia.objects.filter(clip=self.clip).exists())
        leftovers = list(Path(self.tmp.name).iterdir())
        self.assertEqual(leftovers, [])

    def test_over_20s_rejected(self):
        self.client.force_login(self.manager)

        response = self.post_file(self.long_path)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SkateClipMedia.objects.filter(clip=self.clip).exists())
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_replacement_reuses_row_and_cleans_old_file(self):
        self.client.force_login(self.manager)
        self.post_file(self.ok_path)
        media = SkateClipMedia.objects.get(clip=self.clip)
        old_name = media.source_file.name
        old_digest = media.source_sha256

        replacement = Path(self.tmp.name).parent / "replacement.mp4"
        subprocess.run(
            [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=568x320:rate=24:duration=1",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", str(replacement),
            ],
            check=True, capture_output=True, timeout=120,
        )
        self.client.post(
            self.url,
            {
                "source": SimpleUploadedFile(replacement.name, replacement.read_bytes()),
                "confirm_replace": "on",
            },
        )
        replacement.unlink(missing_ok=True)

        media.refresh_from_db()
        self.assertEqual(SkateClipMedia.objects.filter(clip=self.clip).count(), 1)
        self.assertNotEqual(media.source_sha256, old_digest)
        self.assertNotEqual(media.source_file.name, old_name)
        root = Path(settings.SKATE_CLIP_SOURCE_ROOT)
        self.assertFalse((root / old_name).exists())
        self.assertTrue((root / media.source_file.name).exists())
