from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from Blogs.models import Category
from boards.models import Board


class BootstrapFreshSiteTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser(
            username="site-owner",
            email="owner@example.com",
            password="test-only-password",
        )

    def test_creates_minimum_boards_and_superuser_owned_categories(self):
        call_command("bootstrap_fresh_site", owner_username=self.owner.username)

        self.assertEqual(
            set(Board.objects.values_list("slug", flat=True)),
            {"skateboard", "music", "coding"},
        )
        self.assertFalse(Board.objects.filter(category=None).exists())
        self.assertEqual(
            set(Board.objects.values_list("category__owner_id", flat=True)),
            {self.owner.pk},
        )

    def test_preserves_existing_board_content(self):
        board = Board.objects.create(
            slug="music",
            name="Hand edited music",
            description="Keep this text",
            glitch_color="#123456",
            sort_order=99,
        )

        call_command("bootstrap_fresh_site", owner_username=self.owner.username)

        board.refresh_from_db()
        self.assertEqual(board.name, "Hand edited music")
        self.assertEqual(board.description, "Keep this text")
        self.assertEqual(board.glitch_color, "#123456")
        self.assertEqual(board.sort_order, 99)
        self.assertEqual(board.category.owner, self.owner)
        self.assertEqual(Board.objects.count(), 3)

    def test_reassigns_existing_board_categories_to_superuser(self):
        previous_owner = get_user_model().objects.create_user(
            username="previous-owner",
            email="previous-owner@example.com",
            password="test-only-password",
        )
        category = Category.objects.create(
            name="Music",
            owner=previous_owner,
            is_nav=False,
        )

        call_command("bootstrap_fresh_site", owner_username=self.owner.username)

        category.refresh_from_db()
        self.assertEqual(category.owner, self.owner)
        self.assertTrue(category.is_nav)
