"""ORM and Admin contracts for accounts_linear stage 2."""

from django.contrib.admin.sites import AdminSite
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase

from accounts.models import MyUser
from boards.access_rules import BoardRole
from boards.admin import BoardAdmin, BoardMembershipObservationAdmin
from boards.models import Board, BoardMembership


class BoardMembershipModelTest(TestCase):
    def setUp(self):
        self.board = Board.objects.create(slug="coding", name="Coding")
        self.user = MyUser.objects.create_user(
            email="member@example.com",
            username="member",
            password="test-password",
        )

    def test_model_roles_match_pure_access_rule_roles(self):
        model_roles = {value for value, _label in BoardMembership.Role.choices}
        self.assertEqual(model_roles, {role.value for role in BoardRole})

    def test_same_user_has_only_one_membership_per_board(self):
        BoardMembership.objects.create(
            board=self.board,
            user=self.user,
            role=BoardMembership.Role.CONTRIBUTOR,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            BoardMembership.objects.create(
                board=self.board,
                user=self.user,
                role=BoardMembership.Role.REVIEWER,
                is_active=False,
            )

    def test_membership_may_be_updated_or_deactivated(self):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.user,
            role=BoardMembership.Role.CONTRIBUTOR,
        )

        membership.role = BoardMembership.Role.EDITOR
        membership.is_active = False
        membership.save(update_fields=["role", "is_active"])

        membership.refresh_from_db()
        self.assertEqual(membership.role, BoardMembership.Role.EDITOR)
        self.assertFalse(membership.is_active)


class BoardMembershipObservationAdminTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.model_admin = BoardMembershipObservationAdmin(
            BoardMembership,
            AdminSite(),
        )

    def request_for(self, user):
        request = self.factory.get("/super_admin/boards/boardmembership/")
        request.user = user
        return request

    def test_active_superuser_can_only_view_memberships(self):
        superuser = MyUser.objects.create_superuser(
            email="root@example.com",
            username="root",
            password="test-password",
        )
        request = self.request_for(superuser)

        self.assertTrue(self.model_admin.has_module_permission(request))
        self.assertTrue(self.model_admin.has_view_permission(request))
        self.assertFalse(self.model_admin.has_add_permission(request))
        self.assertFalse(self.model_admin.has_change_permission(request))
        self.assertFalse(self.model_admin.has_delete_permission(request))

    def test_dashboard_user_cannot_observe_cross_board_memberships(self):
        dashboard_user = MyUser.objects.create_user(
            email="dashboard@example.com",
            username="dashboard",
            password="test-password",
            is_active=True,
            is_dashboard_user=True,
        )
        request = self.request_for(dashboard_user)

        self.assertFalse(self.model_admin.has_module_permission(request))
        self.assertFalse(self.model_admin.has_view_permission(request))


class BoardAdminStructurePermissionTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.model_admin = BoardAdmin(Board, AdminSite())

    def request_for(self, user):
        request = self.factory.get("/dashboard/boards/board/")
        request.user = user
        return request

    def test_active_superuser_can_add_and_delete_board(self):
        superuser = MyUser.objects.create_superuser(
            email="board-root@example.com",
            username="board-root",
            password="test-password",
        )
        request = self.request_for(superuser)

        self.assertTrue(self.model_admin.has_add_permission(request))
        self.assertTrue(self.model_admin.has_delete_permission(request))

    def test_dashboard_user_cannot_add_or_delete_board(self):
        dashboard_user = MyUser.objects.create_user(
            email="board-dashboard@example.com",
            username="board-dashboard",
            password="test-password",
            is_active=True,
            is_dashboard_user=True,
        )
        request = self.request_for(dashboard_user)

        self.assertFalse(self.model_admin.has_add_permission(request))
        self.assertFalse(self.model_admin.has_delete_permission(request))
