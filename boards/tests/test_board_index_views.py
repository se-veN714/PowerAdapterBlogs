"""Board Index 分派视图的聚焦行为测试。

覆盖：
- /boards/<slug>/ 按 slug 分派三板内容与模板；未知/下线 slug → 404
- Skateboard：homies / selected_homie / clip_list 真实数据渲染；公开过滤不泄露非公开 clip
- homie-line htmx 端点返回 Selected Line 片段
- Music / Coding：archive 与列表数据驱动渲染，无数据时优雅空态
"""

import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from Blogs.models import Category, Post
from boards.models import (
    AppleRecord,
    Board,
    BoardAccessRequest,
    BoardMembership,
    CodingExperiment,
    CodingPrinciple,
    CodingProject,
    SkateClip,
    SkateHomie,
    SpotifyRecord,
)


def _board(slug, name="Board", active=True, **kwargs):
    return Board.objects.create(
        slug=slug,
        name=name,
        is_active=active,
        **kwargs,
    )


class BoardIndexDispatchTests(TestCase):
    def test_home_context_excludes_active_boards_without_an_index(self):
        unsupported = _board("journal")

        response = self.client.get(reverse("index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(unsupported, list(response.context["boards"]))

    def test_unknown_slug_returns_404(self):
        response = self.client.get(reverse("boards:index", args=["nope"]))
        self.assertEqual(response.status_code, 404)

    def test_inactive_board_returns_404(self):
        _board("skateboard", active=False)
        response = self.client.get(reverse("boards:index", args=["skateboard"]))
        self.assertEqual(response.status_code, 404)

    def test_skateboard_renders_data_driven(self):
        board = _board("skateboard")
        homie = SkateHomie.objects.create(
            board=board,
            node_index=1,
            name="Fuminori",
            location="Kunming",
            joined_at=datetime.date(2024, 1, 1),
        )
        SkateClip.objects.create(
            homie=homie,
            order=1,
            title="Fakie Heel",
            is_public=True,
            filmed_at=datetime.date(2024, 6, 12),
            duration=datetime.timedelta(seconds=4),
        )
        response = self.client.get(reverse("boards:index", args=["skateboard"]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("FUMINORI", content)
        self.assertIn("FAKIE HEEL", content)
        # duration 格式化为 mm:ss
        self.assertIn("00:04", content)

    def test_skateboard_hides_non_public_clip(self):
        board = _board("skateboard")
        homie = SkateHomie.objects.create(
            board=board,
            node_index=1,
            name="Fuminori",
            joined_at=datetime.date(2024, 1, 1),
        )
        SkateClip.objects.create(
            homie=homie, order=1, title="Secret Clip", is_public=False
        )
        response = self.client.get(reverse("boards:index", args=["skateboard"]))
        self.assertNotIn("SECRET CLIP", response.content.decode())

    def test_homie_line_endpoint_returns_fragment(self):
        board = _board("skateboard")
        homie = SkateHomie.objects.create(
            board=board,
            node_index=3,
            name="Jimmy Cao",
            joined_at=datetime.date(2024, 1, 1),
        )
        SkateClip.objects.create(homie=homie, order=1, title="Bs Flip", is_public=True)
        url = reverse("boards:homie-line", args=[board.slug, 3])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("BS FLIP", response.content.decode())

    def test_homie_line_unknown_node_404(self):
        _board("skateboard")
        url = reverse("boards:homie-line", args=["skateboard", 99])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_skate_clip_list_is_public_and_newest_filmed_first(self):
        board = _board("skateboard")
        homie = SkateHomie.objects.create(
            board=board,
            node_index=1,
            name="Maria",
            joined_at=datetime.date(2024, 1, 1),
        )
        SkateClip.objects.create(
            homie=homie,
            title="Older Public",
            filmed_at=datetime.date(2024, 1, 1),
            is_public=True,
        )
        SkateClip.objects.create(
            homie=homie,
            title="Newest Public",
            filmed_at=datetime.date(2025, 1, 1),
            is_public=True,
        )
        SkateClip.objects.create(
            homie=homie,
            title="Private Clip",
            filmed_at=datetime.date(2026, 1, 1),
            is_public=False,
        )

        response = self.client.get(reverse("boards:skate-clip-list"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(content.index("NEWEST PUBLIC"), content.index("OLDER PUBLIC"))
        self.assertNotIn("PRIVATE CLIP", content)

    def test_skateboard_cycle_renders_both_portraits_in_shared_box(self):
        board = _board("skateboard")
        homie = SkateHomie.objects.create(
            board=board,
            node_index=1,
            name="Maria",
            joined_at=datetime.date(2024, 1, 1),
        )
        SkateClip.objects.create(homie=homie, order=1, title="First", is_public=True)
        SkateClip.objects.create(homie=homie, order=2, title="Second", is_public=True)

        response = self.client.get(reverse("boards:index", args=["skateboard"]))

        self.assertContains(response, "FIRST")
        self.assertContains(response, "SECOND")
        self.assertContains(response, 'class="sk-clip-pair reveal"', html=False)

    def test_music_renders_archive_data_driven(self):
        board = _board("music")
        SpotifyRecord.objects.create(
            board=board,
            title="2025 Wrap",
            year=2025,
            label="TOTAL",
            value="32,481",
            unit="MIN",
            kind="total",
            display_order=0,
        )
        SpotifyRecord.objects.create(
            board=board,
            title="2025 Wrap",
            year=2025,
            label="POST-ROCK",
            kind="tag",
            display_order=1,
        )
        response = self.client.get(reverse("boards:index", args=["music"]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("2025", content)
        self.assertIn("32,481 MIN", content)
        self.assertIn("POST-ROCK", content)

    def test_music_exposes_ranked_spotify_and_apple_contract(self):
        board = _board("music")
        SpotifyRecord.objects.create(
            board=board,
            title="Spotify Wrapped 2025",
            year=2025,
            label="Artist A",
            value="120",
            kind="top_artist",
            rank=1,
            play_count=8,
            minutes=120,
            display_order=1,
        )
        SpotifyRecord.objects.create(
            board=board,
            title="Spotify Wrapped 2025",
            year=2025,
            label="Track A",
            value="Artist A",
            kind="top_track",
            rank=1,
            play_count=4,
            minutes=20,
            display_order=1,
        )
        AppleRecord.objects.create(
            board=board,
            title="Apple Music 2026.07",
            scope="monthly",
            year=2026,
            month=7,
            label="TOTAL MINUTES",
            value="4720",
            kind="total",
            minutes=4720,
        )
        AppleRecord.objects.create(
            board=board,
            title="Apple Music 2026.07",
            scope="monthly",
            year=2026,
            month=7,
            label="Artist B",
            kind="top_artist",
            rank=1,
            minutes=1181,
            display_order=1,
        )

        response = self.client.get(reverse("boards:index", args=["music"]))

        self.assertEqual(response.context["spotify_top_artists"][0]["name"], "Artist A")
        self.assertEqual(response.context["spotify_top_tracks"][0]["plays"], 4)
        self.assertEqual(response.context["apple_current"]["minutes_display"], "4,720")
        self.assertEqual(
            response.context["apple_current"]["top_artists"][0]["name"],
            "Artist B",
        )

    def test_coding_renders_lists_data_driven(self):
        board = _board("coding")
        CodingProject.objects.create(
            board=board,
            index=1,
            name="Monitor",
            description="Training log viewer",
            stack="Python / SSE",
            year=2026,
            status="in use",
        )
        CodingPrinciple.objects.create(
            board=board,
            index=1,
            title="Need before framework",
            body="Start from the problem.",
        )
        CodingExperiment.objects.create(
            board=board,
            date=datetime.date(2026, 7, 1),
            title="HTMX partial refresh",
        )
        response = self.client.get(reverse("boards:index", args=["coding"]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("MONITOR", content)
        self.assertIn("NEED BEFORE FRAMEWORK", content)
        self.assertIn("HTMX partial refresh", content)

    def test_coding_exposes_repository_and_demo_link_contract(self):
        board = _board("coding")
        CodingProject.objects.create(
            board=board,
            index=1,
            name="Repository",
            project_type=CodingProject.ProjectType.GITHUB,
            repository_url="https://github.com/example/repository",
            demo_url="https://example.test/demo",
            is_featured=True,
        )

        response = self.client.get(reverse("boards:index", args=["coding"]))

        project = response.context["projects"][0]
        self.assertEqual(project["project_type"], "github")
        self.assertEqual(
            project["repository_url"],
            "https://github.com/example/repository",
        )
        self.assertEqual(project["demo_url"], "https://example.test/demo")
        self.assertTrue(project["is_featured"])


class BoardIndexArticleFlowTests(TestCase):
    def setUp(self):
        self.author = get_user_model().objects.create_user(
            username="board-author",
            email="board-author@example.test",
            password="test-pass-123",
            is_active=True,
        )
        self.category = Category.objects.create(
            name="Coding Dispatches",
            owner=self.author,
        )
        self.board = _board(
            "coding",
            name="Coding",
            category=self.category,
        )

    def create_post(
        self,
        title,
        *,
        status=Post.STATUS_NORMAL,
        visibility=Post.VISIBILITY_PUBLIC,
    ):
        return Post.objects.create(
            title=title,
            slug=title.lower().replace(" ", "-"),
            content="Body",
            status=status,
            visibility=visibility,
            category=self.category,
            owner=self.author,
        )

    def test_index_uses_public_post_queryset_and_renders_shared_components(self):
        self.create_post("Public Dispatch")
        self.create_post("Private Draft", status=Post.STATUS_DRAFT)
        self.create_post(
            "Staff Dispatch",
            visibility=Post.VISIBILITY_STAFF_ONLY,
        )

        response = self.client.get(reverse("boards:index", args=["coding"]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Public Dispatch")
        self.assertNotContains(response, "Private Draft")
        self.assertNotContains(response, "Staff Dispatch")
        self.assertContains(response, "DISPATCHES")
        self.assertContains(response, "JOIN CODING")
        self.assertEqual(response.context["board_participation_state"], "anonymous")
        self.assertEqual(
            response.context["board_posts_url"],
            reverse("Blogs:category_list", args=[self.category.pk]),
        )

    def test_contributor_cta_opens_post_form_with_safe_board_preselection(self):
        contributor = get_user_model().objects.create_user(
            username="coding-contributor",
            email="coding-contributor@example.test",
            password="test-pass-123",
            is_active=True,
        )
        BoardMembership.objects.create(
            board=self.board,
            user=contributor,
            role=BoardMembership.Role.CONTRIBUTOR,
        )
        self.client.force_login(contributor)

        index_response = self.client.get(reverse("boards:index", args=["coding"]))

        self.assertEqual(index_response.context["board_participation_state"], "member")
        self.assertEqual(
            index_response.context["board_participation_url"],
            f'{reverse("Blogs:post_create")}?board=coding',
        )
        form_response = self.client.get(
            index_response.context["board_participation_url"]
        )
        self.assertEqual(form_response.status_code, 200)
        self.assertEqual(
            form_response.context["form"].initial["category"],
            self.category,
        )

    def test_inactive_category_hides_public_link_and_create_cta(self):
        contributor = get_user_model().objects.create_user(
            username="inactive-category-contributor",
            email="inactive-category-contributor@example.test",
            password="test-pass-123",
            is_active=True,
        )
        BoardMembership.objects.create(
            board=self.board,
            user=contributor,
            role=BoardMembership.Role.CONTRIBUTOR,
        )
        self.category.status = Category.STATUS_DELETE
        self.category.save(update_fields=["status"])
        self.client.force_login(contributor)

        response = self.client.get(reverse("boards:index", args=["coding"]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["board_posts_url"])
        self.assertNotContains(response, "查看全部文章")
        self.assertEqual(response.context["board_participation_state"], "member")
        self.assertNotEqual(
            response.context["board_participation_url"],
            f'{reverse("Blogs:post_create")}?board=coding',
        )

    def test_missing_category_does_not_offer_or_preselect_post_creation(self):
        contributor = get_user_model().objects.create_user(
            username="missing-category-contributor",
            email="missing-category-contributor@example.test",
            password="test-pass-123",
            is_active=True,
        )
        BoardMembership.objects.create(
            board=self.board,
            user=contributor,
            role=BoardMembership.Role.CONTRIBUTOR,
        )
        self.board.category = None
        self.board.save(update_fields=["category"])
        valid_category = Category.objects.create(
            name="Music Dispatches",
            owner=self.author,
        )
        valid_board = _board("music", name="Music", category=valid_category)
        BoardMembership.objects.create(
            board=valid_board,
            user=contributor,
            role=BoardMembership.Role.CONTRIBUTOR,
        )
        self.client.force_login(contributor)

        index_response = self.client.get(reverse("boards:index", args=["coding"]))
        form_response = self.client.get(
            f'{reverse("Blogs:post_create")}?board=coding'
        )

        self.assertNotEqual(
            index_response.context["board_participation_url"],
            f'{reverse("Blogs:post_create")}?board=coding',
        )
        self.assertIsNone(form_response.context["form"].initial.get("category"))

    def test_duplicate_category_mapping_does_not_offer_or_preselect_creation(self):
        contributor = get_user_model().objects.create_user(
            username="duplicate-category-contributor",
            email="duplicate-category-contributor@example.test",
            password="test-pass-123",
            is_active=True,
        )
        BoardMembership.objects.create(
            board=self.board,
            user=contributor,
            role=BoardMembership.Role.CONTRIBUTOR,
        )
        _board("music", name="Music", category=self.category)
        valid_category = Category.objects.create(
            name="Skateboard Dispatches",
            owner=self.author,
        )
        valid_board = _board(
            "skateboard",
            name="Skateboard",
            category=valid_category,
        )
        BoardMembership.objects.create(
            board=valid_board,
            user=contributor,
            role=BoardMembership.Role.CONTRIBUTOR,
        )
        self.client.force_login(contributor)

        index_response = self.client.get(reverse("boards:index", args=["coding"]))
        form_response = self.client.get(
            f'{reverse("Blogs:post_create")}?board=coding'
        )

        self.assertNotEqual(
            index_response.context["board_participation_url"],
            f'{reverse("Blogs:post_create")}?board=coding',
        )
        self.assertIsNone(form_response.context["form"].initial.get("category"))

    def test_pending_and_eligible_states_use_board_scoped_access_url(self):
        applicant = get_user_model().objects.create_user(
            username="board-applicant",
            email="board-applicant@example.test",
            password="test-pass-123",
            is_active=True,
        )
        applicant.user_permissions.add(
            Permission.objects.get(
                codename="apply_board_access",
                content_type__app_label="boards",
            )
        )
        self.client.force_login(applicant)

        eligible = self.client.get(reverse("boards:index", args=["coding"]))
        self.assertEqual(eligible.context["board_participation_state"], "eligible")
        access_response = self.client.get(
            eligible.context["board_participation_url"]
        )
        self.assertEqual(access_response.context["form"].initial["board"], self.board)

        BoardAccessRequest.objects.create(
            board=self.board,
            applicant=applicant,
            requested_role=BoardMembership.Role.CONTRIBUTOR,
        )
        pending = self.client.get(reverse("boards:index", args=["coding"]))
        self.assertEqual(pending.context["board_participation_state"], "pending")

    def test_music_and_skateboard_indices_render_the_same_public_sections(self):
        for slug, name in (("music", "Music"), ("skateboard", "Skateboard")):
            with self.subTest(slug=slug):
                category = Category.objects.create(
                    name=f"{name} Dispatches",
                    owner=self.author,
                )
                _board(slug, name=name, category=category)
                response = self.client.get(reverse("boards:index", args=[slug]))
                self.assertContains(response, "DISPATCHES")
                self.assertContains(response, f"JOIN {name.upper()}")
