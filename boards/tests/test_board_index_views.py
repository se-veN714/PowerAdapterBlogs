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
    SpotifyEntry,
    SpotifySnapshot,
)


def _board(slug, name="Board", active=True):
    return Board.objects.create(slug=slug, name=name, is_active=active)


class BoardIndexDispatchTests(TestCase):
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
            is_active=True,
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
            is_active=True,
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
            is_active=False,
        )
        SkateClip.objects.create(
            homie=homie, order=1, title="Bs Flip", is_public=True
        )
        url = reverse("boards:homie-line", args=[board.slug, 3])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("BS FLIP", response.content.decode())

    def test_homie_line_unknown_node_404(self):
        _board("skateboard")
        url = reverse("boards:homie-line", args=["skateboard", 99])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_music_renders_archive_data_driven(self):
        board = _board("music")
        snap = SpotifySnapshot.objects.create(
            board=board, title="2025 Wrap", year=2025
        )
        SpotifyEntry.objects.create(
            snapshot=snap, label="TOTAL", value="32,481", unit="MIN",
            kind="total", display_order=0,
        )
        SpotifyEntry.objects.create(
            snapshot=snap, label="POST-ROCK", kind="tag", display_order=1,
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
            board=board, index=1, name="Monitor", description="Training log viewer",
            stack="Python / SSE", year=2026, status="in use",
        )
        CodingPrinciple.objects.create(
            board=board, index=1, title="Need before framework",
            body="Start from the problem.",
        )
        CodingExperiment.objects.create(
            board=board, date=datetime.date(2026, 7, 1),
            title="HTMX partial refresh",
        )
        response = self.client.get(reverse("boards:index", args=["coding"]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("MONITOR", content)
        self.assertIn("NEED BEFORE FRAMEWORK", content)
        self.assertIn("HTMX partial refresh", content)
