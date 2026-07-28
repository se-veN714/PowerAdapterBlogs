"""Board Index 分派视图的聚焦行为测试。

覆盖：
- /boards/<slug>/ 按 slug 分派三板内容与模板；未知/下线 slug → 404
- Skateboard：homies / selected_homie / clip_list 真实数据渲染；公开过滤不泄露非公开 clip
- homie-line htmx 端点返回 Selected Line 片段
- Music / Coding：archive 与列表数据驱动渲染，无数据时优雅空态
"""

import datetime

from django.test import TestCase
from django.urls import reverse

from boards.models import (
    Board,
    CodingExperiment,
    CodingPrinciple,
    CodingProject,
    SkateClip,
    SkateHomie,
    SpotifyRecord,
)


def _board(slug, name="Board", active=True):
    return Board.objects.create(slug=slug, name=name, is_active=active)


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
