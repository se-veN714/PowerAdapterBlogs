"""Board Index 内容模型的行为测试（聚焦）。

覆盖：抽象基类不建表、SkateHomie↔BoardMembership 的 M2M 仅展示关联、
唯一约束、is_public 过滤、Music 相关名展开、Coding 三模型与排序。
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from boards.models import (
    AppleRecord,
    Board,
    BoardMembership,
    ClipStatus,
    CodingExperiment,
    CodingPrinciple,
    CodingProject,
    MusicScope,
    SkateClip,
    SkateHomie,
    SpotifyRecord,
)


class BoardIndexModelStructureTests(TestCase):
    """无 DB 副作用的结构性断言。"""

    def test_music_base_is_abstract(self):
        from boards.models import MusicRecordBase

        self.assertTrue(MusicRecordBase._meta.abstract)

    def test_music_related_name_expands_per_class(self):
        board = Board.objects.create(slug="music", name="Music")
        spotify = SpotifyRecord.objects.create(
            board=board, title="2025", year=2025, label="X", value="1")
        apple = AppleRecord.objects.create(
            board=board, title="2026-06", year=2026, month=6,
            scope=MusicScope.MONTHLY, label="Y", value="2"
        )
        self.assertIn(spotify, board.spotifyrecords.all())
        self.assertIn(apple, board.applerecords.all())


class SkateboardModelTests(TestCase):
    def setUp(self):
        self.board = Board.objects.create(slug="skateboard", name="Skateboard")
        self.user = get_user_model().objects.create_user(
            username="crew", email="crew@example.com", password="x"
        )

    def test_homie_membership_m2m_display_only(self):
        membership = BoardMembership.objects.create(
            board=self.board, user=self.user, role=BoardMembership.Role.MANAGER
        )
        homie = SkateHomie.objects.create(
            board=self.board, node_index=1, name="FUMINORI", joined_at="2024-01-01"
        )
        homie.memberships.add(membership)
        self.assertIn(membership, homie.memberships.all())
        self.assertIn(homie, membership.homies.all())

    def test_unique_node_index_per_board(self):
        SkateHomie.objects.create(
            board=self.board, node_index=1, name="A", joined_at="2024-01-01"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SkateHomie.objects.create(
                    board=self.board, node_index=1, name="B", joined_at="2024-02-01"
                )

    def test_clip_is_public_filter(self):
        homie = SkateHomie.objects.create(
            board=self.board,
            node_index=1,
            name="A",
            joined_at="2024-01-01",
        )
        SkateClip.objects.create(
            homie=homie, order=1, title="PUBLIC", is_public=True, status=ClipStatus.LANDED
        )
        SkateClip.objects.create(
            homie=homie, order=2, title="HIDDEN", is_public=False, status=ClipStatus.LANDED
        )
        public = homie.clips.filter(is_public=True)
        self.assertEqual(public.count(), 1)
        self.assertEqual(public.first().title, "PUBLIC")


class MusicModelTests(TestCase):
    def setUp(self):
        self.board = Board.objects.create(slug="music", name="Music")

    def test_spotify_record_ordering(self):
        SpotifyRecord.objects.create(
            board=self.board, title="2025", year=2025,
            label="TOP TRACK", value="X", display_order=2)
        SpotifyRecord.objects.create(
            board=self.board, title="2025", year=2025,
            label="HEIGHT", value="1.8", display_order=1)
        labels = list(
            SpotifyRecord.objects.filter(board=self.board)
            .order_by("display_order")
            .values_list("label", flat=True)
        )
        self.assertEqual(labels, ["HEIGHT", "TOP TRACK"])


class CodingModelTests(TestCase):
    def setUp(self):
        self.board = Board.objects.create(slug="coding", name="Coding")

    def test_coding_models_create_and_ordering(self):
        CodingProject.objects.create(
            board=self.board, index=1, name="MONITOR", year=2026, status="IN USE", is_active=True
        )
        CodingPrinciple.objects.create(
            board=self.board, index=1, title="NEED BEFORE FRAMEWORK"
        )
        CodingExperiment.objects.create(
            board=self.board, date="2026-07-01", title="HTMX partial"
        )
        self.assertEqual(CodingProject.objects.count(), 1)
        self.assertEqual(CodingPrinciple.objects.count(), 1)
        CodingExperiment.objects.create(
            board=self.board, date="2026-08-01", title="later"
        )
        self.assertEqual(CodingExperiment.objects.first().title, "later")
