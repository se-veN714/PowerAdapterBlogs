import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from boards.models import (
    AppleRecord,
    Board,
    BoardMembership,
    CodingProject,
    SkateClip,
    SkateClipMedia,
    SkateHomie,
    SpotifyRecord,
)


User = get_user_model()


class BoardContentManagementTests(TestCase):
    def setUp(self):
        self.skateboard = Board.objects.create(
            slug="skateboard",
            name="Skateboard",
        )
        self.music = Board.objects.create(slug="music", name="Music")
        self.coding = Board.objects.create(slug="coding", name="Coding")
        self.manager = self._user("manager")
        self.reviewer = self._user("reviewer")
        self.ordinary = self._user("ordinary")
        BoardMembership.objects.create(
            board=self.skateboard,
            user=self.manager,
            role=BoardMembership.Role.MANAGER,
        )
        BoardMembership.objects.create(
            board=self.music,
            user=self.manager,
            role=BoardMembership.Role.MANAGER,
        )
        BoardMembership.objects.create(
            board=self.coding,
            user=self.manager,
            role=BoardMembership.Role.MANAGER,
        )
        BoardMembership.objects.create(
            board=self.music,
            user=self.reviewer,
            role=BoardMembership.Role.REVIEWER,
        )
        self.homie = SkateHomie.objects.create(
            board=self.skateboard,
            node_index=1,
            name="Manager Test",
            joined_at=datetime.date(2026, 1, 1),
        )

    @staticmethod
    def _user(username):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password="test-password",
            is_active=True,
        )

    def test_anonymous_is_redirected_and_non_manager_is_denied(self):
        url = reverse("boards:music-manage-list", args=["spotify"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.reviewer)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_manager_can_create_spotify_record(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("boards:music-manage-create", args=["spotify"]),
            {
                "title": "Spotify Wrapped 2025",
                "scope": "yearly",
                "year": 2025,
                "month": "",
                "kind": "top_track",
                "label": "Track",
                "value": "Artist",
                "value2": "",
                "unit": "",
                "rank": 1,
                "play_count": 4,
                "minutes": 20,
                "note": "",
                "external_url": "https://open.spotify.com/track/example",
                "display_order": 1,
            },
        )

        self.assertRedirects(
            response,
            reverse("boards:music-manage-list", args=["spotify"]),
        )
        record = SpotifyRecord.objects.get(label="Track")
        self.assertEqual(record.board, self.music)
        self.assertEqual(record.rank, 1)

    def test_manager_can_create_and_filter_skate_clip(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("boards:skate-manage-create"),
            {
                "homie": self.homie.pk,
                "order": 2,
                "title": "Kickflip",
                "category": "rotation",
                "spot": "Local Park",
                "filmed_at": "2026-08-04",
                "duration": "00:00:05",
                "status": "landed",
                "notes": "Clean",
                "video_url": "https://example.test/kickflip.mp4",
                "thumbnail_url": "https://example.test/kickflip.webp",
                "hud_type": "arc",
                "hud_label": "ROTATION 360",
                "timecode": "00:00:01:10",
                "is_public": "on",
            },
        )

        self.assertRedirects(response, reverse("boards:skate-manage-list"))
        clip = SkateClip.objects.get(title="Kickflip")
        self.assertEqual(clip.homie, self.homie)

        response = self.client.get(
            reverse("boards:skate-manage-list"),
            {"homie": self.homie.pk, "query": "Kick", "visibility": "public"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["records"].paginator.count, 1)

    def test_manager_can_delete_skate_clip_and_receives_notification(self):
        clip = SkateClip.objects.create(
            homie=self.homie,
            order=1,
            title="Delete Me",
        )
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("boards:skate-manage-delete", args=[clip.pk]),
            follow=True,
        )

        self.assertRedirects(response, reverse("boards:skate-manage-list"))
        self.assertFalse(SkateClip.objects.filter(pk=clip.pk).exists())
        self.assertContains(response, "滑板片段已删除。")

    def test_skate_list_distinguishes_first_upload_from_replacement(self):
        without_media = SkateClip.objects.create(
            homie=self.homie,
            order=1,
            title="Needs Source",
        )
        with_media = SkateClip.objects.create(
            homie=self.homie,
            order=2,
            title="Has Source",
        )
        SkateClipMedia.objects.create(clip=with_media, uploaded_by=self.manager)
        self.client.force_login(self.manager)

        response = self.client.get(reverse("boards:skate-manage-list"))

        self.assertContains(response, ">UPLOAD</a>")
        self.assertContains(response, ">REPLACE MEDIA</a>")
        self.assertContains(response, str(without_media.order).zfill(2))

    def test_management_links_follow_board_policy(self):
        self.client.force_login(self.manager)

        home = self.client.get(reverse("index"))
        labels = [link["label"] for link in home.context["board_management_links"]]
        self.assertEqual(
            labels,
            [
                "Skateboard · Clips",
                "Music · Spotify",
                "Music · Apple Music",
                "Coding · Projects",
            ],
        )

        board_index = self.client.get(
            reverse("boards:index", args=["skateboard"]),
        )
        self.assertContains(board_index, "进入 CRUD 工作区")
        self.assertContains(board_index, reverse("boards:skate-manage-list"))

        self.client.force_login(self.reviewer)
        board_index = self.client.get(reverse("boards:index", args=["music"]))
        self.assertNotContains(board_index, "进入 CRUD 工作区")

    def test_provider_scoping_prevents_cross_model_update(self):
        record = AppleRecord.objects.create(
            board=self.music,
            title="Apple 2026.07",
            scope="monthly",
            year=2026,
            month=7,
            label="TOTAL",
            value="4720",
            kind="total",
        )
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("boards:music-manage-update", args=["spotify", record.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_music_list_uses_frontend_contract_and_paginated_records(self):
        for index in range(31):
            SpotifyRecord.objects.create(
                board=self.music,
                title=f"Wrapped {index}",
                scope="yearly",
                year=2025,
                kind="top_track",
                label=f"Track {index}",
                value="Artist",
                display_order=index,
            )
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("boards:music-manage-list", args=["spotify"]),
            {"query": "Track", "year": "2025"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/boards/manage/music/list.html")
        self.assertEqual(response.context["records"].paginator.count, 31)
        self.assertEqual(response.context["records"].number, 1)
        self.assertEqual(response.context["filters"]["query"], "Track")

    def test_manager_can_create_local_coding_project(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("boards:coding-manage-create"),
            {
                "index": 1,
                "name": "PAdif",
                "description": "Local document version workspace",
                "stack": "HTML / LocalStorage",
                "year": 2026,
                "status": "active",
                "project_type": "local_tool",
                "repository_url": "",
                "demo_url": "",
                "is_featured": "on",
                "is_active": "on",
                "order": 1,
            },
        )

        self.assertRedirects(response, reverse("boards:coding-manage-list"))
        project = CodingProject.objects.get(name="PAdif")
        self.assertEqual(project.board, self.coding)
        self.assertEqual(project.project_type, "local_tool")

    def test_coding_list_filters_query_type_and_year_with_page_contract(self):
        CodingProject.objects.create(
            board=self.coding,
            index=1,
            name="Current Padif",
            stack="HTML",
            year=2026,
            project_type=CodingProject.ProjectType.LOCAL_TOOL,
        )
        CodingProject.objects.create(
            board=self.coding,
            index=2,
            name="Old Padif",
            stack="HTML",
            year=2025,
            project_type=CodingProject.ProjectType.LOCAL_TOOL,
        )
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("boards:coding-manage-list"),
            {"query": "Padif", "project_type": "local_tool", "year": "2026"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/boards/manage/coding/list.html")
        self.assertEqual(response.context["records"].paginator.count, 1)
        self.assertEqual(response.context["records"][0].name, "Current Padif")
        self.assertEqual(response.context["filters"]["year"], "2026")

    def test_padif_shell_is_public_and_contains_no_server_form(self):
        response = self.client.get(reverse("boards:padif-local"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LOCAL BROWSER WORKSPACE")
        self.assertNotContains(response, "<form", html=False)
