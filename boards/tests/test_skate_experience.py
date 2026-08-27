from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from boards.content_forms import SkateClipForm
from boards.models import (
    Board,
    BoardMembership,
    SkateClip,
    SkateClipMedia,
    SkateHomie,
)


class SkateClipFormTests(TestCase):
    def test_form_exposes_client_preflight_and_content_format(self):
        form = SkateClipForm()
        self.assertIn("source", form.fields)
        self.assertIn("clip_format", form.fields)
        self.assertEqual(form.fields["source"].widget.attrs["data-skate-max-duration-ms"], "20000")

    def test_legacy_post_defaults_content_format_to_clip(self):
        board = Board.objects.create(slug="skateboard", name="Skateboard")
        homie = SkateHomie.objects.create(
            board=board, node_index=1, name="Tester", joined_at="2026-08-01"
        )
        form = SkateClipForm(
            data={
                "homie": homie.pk,
                "order": 0,
                "title": "Legacy Ollie",
                "status": "landed",
                "is_public": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["clip_format"], "clip")

    def test_location_coordinates_must_be_a_pair(self):
        board = Board.objects.create(slug="skateboard", name="Skateboard")
        homie = SkateHomie.objects.create(
            board=board, node_index=1, name="Tester", joined_at="2026-08-01"
        )
        form = SkateClipForm(
            data={
                "homie": homie.pk,
                "order": 0,
                "title": "Ollie",
                "clip_format": "clip",
                "category": "rotation",
                "spot": "Kunming",
                "spot_longitude": "102.700000",
                "status": "landed",
                "is_public": True,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("地图坐标不完整", form.errors["spot"][0])

    def test_location_coordinates_are_persistable(self):
        board = Board.objects.create(slug="skateboard", name="Skateboard")
        homie = SkateHomie.objects.create(
            board=board, node_index=1, name="Tester", joined_at="2026-08-01"
        )
        clip = SkateClip.objects.create(
            homie=homie,
            title="Line",
            clip_format="line",
            spot_longitude=Decimal("102.700000"),
            spot_latitude=Decimal("25.040000"),
        )
        self.assertEqual(clip.clip_format, "line")
        self.assertEqual(clip.spot_latitude, Decimal("25.040000"))


class SkateClipCreateExperienceTests(TestCase):
    def setUp(self):
        self.board = Board.objects.create(
            slug="skateboard", name="Skateboard", glitch_color="#ff4d5e"
        )
        self.homie = SkateHomie.objects.create(
            board=self.board, node_index=1, name="Tester", joined_at="2026-08-01"
        )
        self.manager = get_user_model().objects.create_user(
            username="skmanager",
            email="sk@example.com",
            password="pw-123456",
            is_active=True,
        )
        BoardMembership.objects.create(
            board=self.board,
            user=self.manager,
            role=BoardMembership.Role.MANAGER,
            is_active=True,
        )
        self.client.force_login(self.manager)
        self.url = reverse("boards:skate-manage-create")

    @override_settings(
        AMAP_JS_API_ENABLED=True,
        AMAP_JS_API_KEY="browser-key",
        AMAP_JS_SECURITY_JSCODE="never-render-this",
    )
    def test_form_renders_integrated_upload_without_secret(self):
        response = self.client.get(self.url)
        self.assertContains(response, "UPLOAD &amp; QUEUE PROCESS")
        self.assertNotContains(response, "SEARCH MAP")
        self.assertContains(response, "输入地点关键词并从联想候选中选择")
        self.assertContains(response, "data-amap-search-panel")
        self.assertContains(response, "KEYWORD / 从高德候选中选择地点")
        self.assertContains(response, 'autocomplete="off"')
        self.assertContains(response, 'placeholder="输入地点关键词并选择高德候选"')
        self.assertNotContains(response, "按 Enter 搜索")
        self.assertContains(response, '<legend class="bm-group__legend"><span>')
        self.assertContains(response, "data-amap-key=\"browser-key\"")
        self.assertNotContains(response, "never-render-this")

    def test_process_intent_requires_source(self):
        response = self.client.post(
            self.url,
            {
                "homie": self.homie.pk,
                "order": 0,
                "title": "Ollie",
                "clip_format": "clip",
                "category": "rotation",
                "status": "landed",
                "is_public": True,
                "intent": "process",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "上传并处理需要选择一个视频原片")
        self.assertFalse(SkateClip.objects.filter(title="Ollie").exists())

    @patch("boards.content_views.ingest_skate_source")
    def test_create_with_source_wires_media_ingestion(self, ingest):
        source = SimpleUploadedFile("line.webm", b"video")
        response = self.client.post(
            self.url,
            {
                "homie": self.homie.pk,
                "order": 0,
                "title": "Morning Line",
                "clip_format": "line",
                "category": "displacement",
                "status": "landed",
                "is_public": True,
                "intent": "process",
                "source": source,
            },
        )
        self.assertEqual(response.status_code, 302)
        clip = SkateClip.objects.get(title="Morning Line")
        ingest.assert_called_once()
        self.assertEqual(ingest.call_args.kwargs["clip"], clip)

    @patch("boards.content_views.ingest_skate_source")
    def test_save_metadata_does_not_ingest_selected_source(self, ingest):
        response = self.client.post(
            self.url,
            {
                "homie": self.homie.pk,
                "order": 0,
                "title": "Draft Line",
                "clip_format": "line",
                "status": "wip",
                "is_public": False,
                "intent": "save",
                "source": SimpleUploadedFile("ignored.webm", b"video"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SkateClip.objects.filter(title="Draft Line").exists())
        ingest.assert_not_called()

    @patch("boards.content_views.ingest_skate_source")
    def test_edit_requires_confirmation_before_replacing_unique_media(self, ingest):
        clip = SkateClip.objects.create(
            homie=self.homie,
            title="Existing Line",
            status="landed",
        )
        SkateClipMedia.objects.create(clip=clip, uploaded_by=self.manager)

        response = self.client.post(
            reverse("boards:skate-manage-update", args=[clip.pk]),
            {
                "homie": self.homie.pk,
                "order": 0,
                "title": clip.title,
                "clip_format": "line",
                "category": "displacement",
                "status": "landed",
                "intent": "process",
                "source": SimpleUploadedFile("replacement.webm", b"video"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "系统不会追加第二个视频")
        ingest.assert_not_called()

    @patch("boards.content_views.requeue_existing_skate_source")
    @patch("boards.content_views.ingest_skate_source")
    def test_edit_can_requeue_existing_source_without_reupload(self, ingest, requeue):
        clip = SkateClip.objects.create(
            homie=self.homie,
            title="Retry Existing Line",
            status="failed",
        )
        SkateClipMedia.objects.create(
            clip=clip,
            uploaded_by=self.manager,
            source_file="source/existing.webm",
        )

        response = self.client.post(
            reverse("boards:skate-manage-update", args=[clip.pk]),
            {
                "homie": self.homie.pk,
                "order": 0,
                "title": clip.title,
                "clip_format": "line",
                "category": "displacement",
                "status": "failed",
                "intent": "process",
            },
        )

        self.assertEqual(response.status_code, 302)
        ingest.assert_not_called()
        requeue.assert_called_once()


class SkatePlayerPresentationTests(TestCase):
    def test_board_index_contains_accessible_player_dialog(self):
        board = Board.objects.create(slug="skateboard", name="Skateboard")
        homie = SkateHomie.objects.create(
            board=board, node_index=1, name="Tester", joined_at="2026-08-01"
        )
        SkateClip.objects.create(
            homie=homie,
            title="Ollie",
            video_url="https://example.test/ollie.webm",
            spot="Kunming Park",
            spot_longitude=Decimal("102.700000"),
            spot_latitude=Decimal("25.040000"),
        )
        response = self.client.get(reverse("boards:index", args=["skateboard"]))
        self.assertContains(response, "data-skate-player")
        self.assertContains(response, "data-skate-longitude=\"102.700000\"")
        self.assertContains(response, "aria-labelledby=\"sk-player-title\"")
