"""Manual permission-test account seeding and navigation contracts."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import MyUser
from Blogs.models import Category
from boards.management.commands.seed_permission_test_users import TEST_USERS
from boards.models import Board, BoardMembership


@override_settings(DEBUG=True)
class SeedPermissionTestUsersCommandTest(TestCase):
    password = "local-manual-test-password"

    def setUp(self):
        owner = MyUser.objects.create_superuser(
            email="seed-owner@example.com",
            username="seed-owner",
            password="owner-password",
        )
        category = Category.objects.create(name="Coding", owner=owner)
        self.board = Board.objects.create(
            slug="coding",
            name="Coding",
            category=category,
        )

    def run_command(self):
        stdout = StringIO()
        call_command(
            "seed_permission_test_users",
            board=self.board.slug,
            password=self.password,
            stdout=stdout,
        )
        return stdout.getvalue()

    def test_creates_one_deterministic_account_for_each_board_role(self):
        output = self.run_command()

        for username, role in TEST_USERS:
            user = MyUser.objects.get(username=username)
            self.assertTrue(user.is_active)
            self.assertTrue(user.is_dashboard_user)
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)
            self.assertTrue(user.check_password(self.password))
            self.assertTrue(
                BoardMembership.objects.filter(
                    board=self.board,
                    user=user,
                    role=role,
                    is_active=True,
                ).exists()
            )

        no_board_user = MyUser.objects.get(username="perm_no_board")
        self.assertTrue(no_board_user.is_dashboard_user)
        self.assertFalse(
            BoardMembership.objects.filter(
                user=no_board_user,
                is_active=True,
            ).exists()
        )
        self.assertIn(self.password, output)

    def test_rerun_updates_instead_of_duplicating_memberships(self):
        self.run_command()
        self.run_command()

        self.assertEqual(
            BoardMembership.objects.filter(board=self.board, is_active=True).count(),
            len(TEST_USERS),
        )


class SeedPermissionTestUsersProductionGuardTest(TestCase):
    @override_settings(DEBUG=False)
    def test_refuses_to_run_outside_debug_mode(self):
        with self.assertRaisesMessage(CommandError, "DEBUG=True"):
            call_command("seed_permission_test_users")


class BackendNavigationTest(TestCase):
    def test_board_role_user_sees_only_dashboard_entry(self):
        user = MyUser.objects.create_user(
            email="member-nav@example.com",
            username="member-nav",
            password="test-password",
            is_active=True,
            is_dashboard_user=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("index"))

        self.assertContains(response, reverse("cus_admin:index"))
        self.assertNotContains(response, reverse("admin:index"))

    def test_superuser_sees_dashboard_and_system_admin_entries(self):
        superuser = MyUser.objects.create_superuser(
            email="root-nav@example.com",
            username="root-nav",
            password="test-password",
        )
        superuser.is_dashboard_user = False
        superuser.save(update_fields=["is_dashboard_user"])
        self.client.force_login(superuser)

        response = self.client.get(reverse("index"))

        self.assertContains(response, reverse("cus_admin:index"))
        self.assertContains(response, reverse("admin:index"))
