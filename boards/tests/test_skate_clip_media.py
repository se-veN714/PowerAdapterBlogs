"""SkateClipMedia S0 测试：模型结构、默认状态、存储路由与路径安全边界。

覆盖 SKATEBOARD_GUIDE §4/§5/§9-S0 验收：
- OneToOne 反向关联、默认状态 uploaded、pipeline_version=1
- 私有原片存储独立于 MEDIA_ROOT 且 url() 拒绝生成公开链接
- 派生存储位于 MEDIA_ROOT/skate/ 且 base_url 指向 /media/skate/
- upload_to 全部服务端 UUID 命名，不受原始文件名影响（无路径穿越）
- orientation 由 FFprobe 宽高派生（portrait/landscape/square/缺失）
- settings 上限默认值（150 MiB / 20 秒）
- Admin 对 superuser 只读（add/change/delete 全部拒绝）
"""

import re
import tempfile
import uuid as uuid_module
from pathlib import Path

from django.conf import settings
from django.contrib import admin as django_admin
from django.core.files.base import ContentFile
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from accounts.models import MyUser
from boards.admin import SkateClipMediaAdmin
from boards.models import (
    Board,
    SkateClip,
    SkateClipMedia,
    SkateClipMediaState,
    SkateClipOrientation,
    SkateHomie,
    derive_skate_orientation,
    skate_delivery_storage,
    skate_source_storage,
    _skate_main_upload_to,
    _skate_poster_upload_to,
    _skate_preview_upload_to,
    _skate_source_upload_to,
)


def make_clip():
    board, _ = Board.objects.get_or_create(slug="skateboard", name="Skateboard")
    homie = SkateHomie.objects.create(
        board=board,
        node_index=SkateHomie.objects.count() + 1,
        name="Tester",
        joined_at="2026-08-01",
    )
    return SkateClip.objects.create(homie=homie, order=0, title="Ollie")


class SkateClipMediaModelTests(TestCase):
    def test_defaults_are_uploaded_and_pipeline_v1(self):
        media = SkateClipMedia.objects.create(clip=make_clip())

        self.assertEqual(media.state, SkateClipMediaState.UPLOADED)
        self.assertEqual(media.pipeline_version, 1)
        self.assertFalse(media.is_ready)
        self.assertEqual(media.error_code, "")
        self.assertIsNone(media.duration_ms)
        self.assertEqual(media.orientation, "")

    def test_one_to_one_reverse_accessor(self):
        clip = make_clip()
        media = SkateClipMedia.objects.create(clip=clip)

        self.assertEqual(media.clip, clip)
        self.assertEqual(clip.media, media)

    def test_media_key_is_server_generated_uuid(self):
        media = SkateClipMedia.objects.create(clip=make_clip())

        self.assertIsInstance(media.media_key, uuid_module.UUID)
        self.assertNotEqual(
            media.media_key,
            SkateClipMedia.objects.create(clip=make_clip()).media_key,
        )

    def test_str_includes_state(self):
        media = SkateClipMedia.objects.create(clip=make_clip())

        self.assertIn("Uploaded", str(media))

    def test_apply_probe_derives_orientation(self):
        media = SkateClipMedia.objects.create(clip=make_clip())

        media.apply_probe(duration_ms=8_500, width=1080, height=1920, frame_rate="30000/1001")

        self.assertEqual(media.duration_ms, 8_500)
        self.assertEqual(media.orientation, SkateClipOrientation.PORTRAIT)
        self.assertEqual(media.frame_rate, "30000/1001")

    def test_uploaded_by_nullable_keeps_row(self):
        user = MyUser.objects.create_user(
            username="uploader",
            email="uploader@example.com",
            password="test-password",
            is_active=True,
        )
        clip = make_clip()
        media = SkateClipMedia.objects.create(clip=clip, uploaded_by=user)

        user.delete()

        media.refresh_from_db()
        self.assertIsNone(media.uploaded_by)
        self.assertEqual(SkateClipMedia.objects.count(), 1)


class DeriveOrientationTests(SimpleTestCase):
    def test_landscape(self):
        self.assertEqual(derive_skate_orientation(1920, 1080), SkateClipOrientation.LANDSCAPE)

    def test_portrait(self):
        self.assertEqual(derive_skate_orientation(1080, 1920), SkateClipOrientation.PORTRAIT)

    def test_square(self):
        self.assertEqual(derive_skate_orientation(1080, 1080), SkateClipOrientation.SQUARE)

    def test_missing_or_invalid_dimensions(self):
        for width, height in ((None, 1080), (1080, None), (0, 0), (-10, 100), ("x", 10), ("", "")):
            with self.subTest(width=width, height=height):
                self.assertEqual(derive_skate_orientation(width, height), "")


class SkateMediaStorageRoutingTests(SimpleTestCase):
    """存储路由的安全断言：私有不可达、派生在公开根之下。"""

    def test_source_root_is_outside_media_root(self):
        source = Path(settings.SKATE_CLIP_SOURCE_ROOT).resolve()
        media = Path(settings.MEDIA_ROOT).resolve()
        self.assertFalse(source.is_relative_to(media))

    def test_source_storage_url_is_forbidden(self):
        storage = skate_source_storage()
        with self.assertRaises(ValueError):
            storage.url("anything.mp4")

    def test_source_storage_writes_under_private_root_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(SKATE_CLIP_SOURCE_ROOT=Path(tmp)):
                storage = skate_source_storage()
                self.assertEqual(Path(storage.location), Path(tmp))

                saved = storage.save("probe.mp4", ContentFile(b"x"))

                self.assertEqual(saved, "probe.mp4")
                self.assertTrue((Path(tmp) / "probe.mp4").exists())

    def test_delivery_storage_serves_under_media_skate(self):
        storage = skate_delivery_storage()

        self.assertEqual(
            Path(storage.location),
            Path(settings.SKATE_CLIP_DELIVERY_ROOT),
        )
        self.assertEqual(storage.base_url, settings.SKATE_CLIP_DELIVERY_URL)
        self.assertTrue(
            Path(settings.SKATE_CLIP_DELIVERY_ROOT)
            .resolve()
            .is_relative_to(Path(settings.MEDIA_ROOT).resolve())
        )

    def test_delivery_url_prefix_is_media_skate(self):
        self.assertEqual(settings.SKATE_CLIP_DELIVERY_URL, "/media/skate/")


class SkateUploadToTests(SimpleTestCase):
    def test_source_upload_to_ignores_client_filename(self):
        media = SkateClipMedia(clip_id=1)

        key = _skate_source_upload_to(media, "../../etc/passwd.MP4")

        self.assertRegex(key, r"^[0-9a-f]{32}\.mp4$")
        self.assertNotIn("etc", key)
        self.assertNotIn("/", key)

    def test_source_upload_to_sanitizes_unsafe_suffix(self):
        media = SkateClipMedia(clip_id=1)

        key = _skate_source_upload_to(media, "clip.mp4;rm -rf")

        self.assertRegex(key, r"^[0-9a-f]{32}\.bin$")

    def test_derived_keys_are_deterministic_per_media_key(self):
        media = SkateClipMedia(clip_id=1, media_key="e1f0" * 8)

        self.assertEqual(_skate_main_upload_to(media, "x"), "delivery/%s/main.webm" % media.media_key)
        self.assertEqual(
            _skate_preview_upload_to(media, "x"),
            "preview/%s/preview.webm" % media.media_key,
        )
        self.assertEqual(_skate_poster_upload_to(media, "x"), "poster/%s.webp" % media.media_key)

    def test_derived_keys_never_embed_client_filename(self):
        media = SkateClipMedia(clip_id=1)
        pattern = re.compile(r"^[a-z0-9\-/]+\.web[mp]$")

        for key in (
            _skate_main_upload_to(media, "../evil.exe"),
            _skate_preview_upload_to(media, "../evil.exe"),
            _skate_poster_upload_to(media, "../evil.exe"),
        ):
            with self.subTest(key=key):
                self.assertRegex(key, pattern)
                self.assertNotIn("evil", key)


class SkateMediaSettingsTests(SimpleTestCase):
    def test_upload_limit_default_150_mib(self):
        self.assertEqual(settings.SKATE_CLIP_MAX_UPLOAD_BYTES, 150 * 1024 * 1024)

    def test_duration_limit_default_20_seconds(self):
        self.assertEqual(settings.SKATE_CLIP_MAX_DURATION_MS, 20_000)


class SkateClipMediaAdminTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.superuser = MyUser.objects.create_user(
            username="root",
            email="root@example.com",
            password="test-password",
            is_active=True,
            is_superuser=True,
        )
        self.model_admin = SkateClipMediaAdmin(SkateClipMedia, django_admin.site)

    def request_for(self, user):
        request = self.factory.get("/")
        request.user = user
        return request

    def test_admin_is_read_only_even_for_superuser(self):
        request = self.request_for(self.superuser)

        self.assertTrue(self.model_admin.has_view_permission(request))
        self.assertFalse(self.model_admin.has_add_permission(request))
        self.assertFalse(self.model_admin.has_change_permission(request))
        media = SkateClipMedia.objects.create(clip=make_clip())
        self.assertFalse(self.model_admin.has_change_permission(request, media))
        self.assertFalse(self.model_admin.has_delete_permission(request, media))

    def test_admin_hidden_from_non_superuser(self):
        user = MyUser.objects.create_user(
            username="plain",
            email="plain@example.com",
            password="test-password",
            is_active=True,
        )
        request = self.request_for(user)

        self.assertFalse(self.model_admin.has_module_permission(request))
        self.assertFalse(self.model_admin.has_view_permission(request))
