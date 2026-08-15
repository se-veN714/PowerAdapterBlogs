from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from boards.content_forms import SkateClipForm
from boards.models import Board, BoardMembership, SkateClip, SkateHomie


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


class AMapProxyTests(TestCase):
    class Upstream:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self):
            return b'{"status":"1"}'

    @override_settings(
        AMAP_JS_API_ENABLED=True,
        AMAP_JS_SECURITY_JSCODE="server-only-secret",
    )
    @patch("boards.amap_proxy.urlopen", return_value=Upstream())
    def test_proxy_injects_secret_only_upstream(self, mocked_urlopen):
        response = self.client.get("/_AMapService/v3/place/text", {"keywords": "park"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "server-only-secret")
        request = mocked_urlopen.call_args.args[0]
        self.assertIn("jscode=server-only-secret", request.full_url)

    @override_settings(AMAP_JS_API_ENABLED=False, AMAP_JS_SECURITY_JSCODE="secret")
    def test_proxy_is_closed_when_disabled(self):
        response = self.client.get("/_AMapService/v3/place/text")
        self.assertEqual(response.status_code, 404)


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
