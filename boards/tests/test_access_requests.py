from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from PowerAdapterBlogs.base_admin import has_dashboard_access
from accounts.models import MyUser
from boards.admin import DashboardBoardAccessRequestAdmin
from boards.models import Board, BoardAccessRequest, BoardMembership
from boards.services import (
    approve_board_access_request,
    reject_board_access_request,
    submit_board_access_request,
)


class BoardAccessRequestTest(TestCase):
    password = "test-password-2026"

    def setUp(self):
        self.applicant = self.create_user("applicant")
        self.other_applicant = self.create_user("other-applicant")
        self.manager = self.create_user("manager")
        self.other_manager = self.create_user("other-manager")
        self.superuser = MyUser.objects.create_superuser(
            username="root",
            email="root@example.test",
            password=self.password,
        )
        apply_permission = Permission.objects.get(codename="apply_board_access")
        self.applicant.user_permissions.add(apply_permission)
        self.other_applicant.user_permissions.add(apply_permission)

        self.board = Board.objects.create(slug="coding", name="Coding")
        self.other_board = Board.objects.create(slug="music", name="Music")
        BoardMembership.objects.create(
            board=self.board,
            user=self.manager,
            role=BoardMembership.Role.MANAGER,
            created_by=self.superuser,
        )
        BoardMembership.objects.create(
            board=self.other_board,
            user=self.other_manager,
            role=BoardMembership.Role.MANAGER,
            created_by=self.superuser,
        )

    def create_user(self, username):
        return MyUser.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password=self.password,
            is_active=True,
        )

    def submit(self, *, applicant=None, board=None, role=None):
        return submit_board_access_request(
            applicant=applicant or self.applicant,
            board=board or self.board,
            requested_role=role or BoardMembership.Role.CONTRIBUTOR,
            reason="I can help.",
        )

    def test_verified_user_can_submit_but_receives_no_membership(self):
        access_request = self.submit()

        self.assertEqual(access_request.status, BoardAccessRequest.Status.PENDING)
        self.assertFalse(
            BoardMembership.objects.filter(
                board=self.board,
                user=self.applicant,
            ).exists()
        )

    def test_user_without_global_application_permission_is_denied(self):
        with self.assertRaises(PermissionDenied):
            self.submit(applicant=self.manager)

    def test_only_one_pending_request_per_user_and_board(self):
        self.submit()

        with self.assertRaisesMessage(ValidationError, "已有一条待审核申请"):
            self.submit(role=BoardMembership.Role.EDITOR)

    def test_manager_approval_creates_membership_in_own_board(self):
        access_request = self.submit(role=BoardMembership.Role.REVIEWER)

        approved = approve_board_access_request(
            access_request=access_request,
            actor=self.manager,
        )

        membership = BoardMembership.objects.get(
            board=self.board,
            user=self.applicant,
        )
        self.assertEqual(membership.role, BoardMembership.Role.REVIEWER)
        self.assertEqual(membership.created_by, self.manager)
        self.assertEqual(approved.status, BoardAccessRequest.Status.APPROVED)
        self.assertEqual(approved.reviewed_by, self.manager)

    def test_role_change_reuses_membership_and_records_previous_role(self):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.applicant,
            role=BoardMembership.Role.CONTRIBUTOR,
            is_active=False,
        )
        access_request = self.submit(role=BoardMembership.Role.EDITOR)

        approved = approve_board_access_request(
            access_request=access_request,
            actor=self.superuser,
        )

        membership.refresh_from_db()
        self.assertEqual(membership.role, BoardMembership.Role.EDITOR)
        self.assertTrue(membership.is_active)
        self.assertEqual(approved.previous_role, BoardMembership.Role.CONTRIBUTOR)
        self.assertEqual(
            BoardMembership.objects.filter(
                board=self.board, user=self.applicant
            ).count(),
            1,
        )

    def test_manager_cannot_restore_an_inactive_membership(self):
        BoardMembership.objects.create(
            board=self.board,
            user=self.applicant,
            role=BoardMembership.Role.CONTRIBUTOR,
            is_active=False,
        )
        access_request = self.submit(role=BoardMembership.Role.EDITOR)

        with self.assertRaisesMessage(PermissionDenied, "只能由 superuser"):
            approve_board_access_request(
                access_request=access_request,
                actor=self.manager,
            )

        access_request.refresh_from_db()
        self.assertEqual(access_request.status, BoardAccessRequest.Status.PENDING)

    def test_manager_cannot_change_an_existing_manager_membership(self):
        BoardMembership.objects.create(
            board=self.board,
            user=self.applicant,
            role=BoardMembership.Role.MANAGER,
        )
        access_request = self.submit(role=BoardMembership.Role.EDITOR)

        with self.assertRaisesMessage(PermissionDenied, "只能由 superuser"):
            approve_board_access_request(
                access_request=access_request,
                actor=self.manager,
            )

    def test_manager_cannot_approve_cross_board_manager_role_or_self(self):
        cross_board = self.submit(board=self.other_board)
        manager_role = self.submit(
            applicant=self.other_applicant,
            role=BoardMembership.Role.MANAGER,
        )
        self.manager.user_permissions.add(
            Permission.objects.get(codename="apply_board_access")
        )
        own_request = self.submit(
            applicant=self.manager,
            role=BoardMembership.Role.EDITOR,
        )

        for access_request in (cross_board, manager_role, own_request):
            with self.assertRaises(PermissionDenied):
                approve_board_access_request(
                    access_request=access_request,
                    actor=self.manager,
                )

    def test_superuser_can_approve_manager_role_but_not_own_request(self):
        access_request = self.submit(role=BoardMembership.Role.MANAGER)

        approve_board_access_request(
            access_request=access_request,
            actor=self.superuser,
        )

        self.assertEqual(
            BoardMembership.objects.get(
                board=self.board,
                user=self.applicant,
            ).role,
            BoardMembership.Role.MANAGER,
        )

        own_request = self.submit(
            applicant=self.superuser,
            board=self.other_board,
            role=BoardMembership.Role.CONTRIBUTOR,
        )
        with self.assertRaises(PermissionDenied):
            approve_board_access_request(
                access_request=own_request,
                actor=self.superuser,
            )

    def test_rejection_does_not_change_membership(self):
        access_request = self.submit(role=BoardMembership.Role.EDITOR)

        rejected = reject_board_access_request(
            access_request=access_request,
            actor=self.manager,
            note="Not yet",
        )

        self.assertEqual(rejected.status, BoardAccessRequest.Status.REJECTED)
        self.assertFalse(
            BoardMembership.objects.filter(
                board=self.board,
                user=self.applicant,
            ).exists()
        )

    def test_superuser_can_close_request_after_applicant_is_disabled(self):
        access_request = self.submit()
        self.applicant.is_active = False
        self.applicant.save(update_fields=["is_active"])

        rejected = reject_board_access_request(
            access_request=access_request,
            actor=self.superuser,
            note="Account disabled",
        )

        self.assertEqual(rejected.status, BoardAccessRequest.Status.REJECTED)

    def test_decision_is_single_use(self):
        access_request = self.submit()
        approve_board_access_request(access_request=access_request, actor=self.manager)

        with self.assertRaisesMessage(ValidationError, "已经处理"):
            reject_board_access_request(
                access_request=access_request,
                actor=self.manager,
            )

    @patch("boards.services.BoardMembership.objects.create")
    def test_membership_failure_rolls_back_decision(self, create_membership):
        create_membership.side_effect = RuntimeError("database write failed")
        access_request = self.submit()

        with self.assertRaises(RuntimeError):
            approve_board_access_request(
                access_request=access_request,
                actor=self.manager,
            )

        access_request.refresh_from_db()
        self.assertEqual(access_request.status, BoardAccessRequest.Status.PENDING)
        self.assertIsNone(access_request.reviewed_by)

    def test_manager_membership_grants_dashboard_shell_not_global_permissions(self):
        self.assertTrue(has_dashboard_access(self.manager))
        self.assertFalse(self.manager.has_perm("accounts.manage_user_accounts"))
        self.assertFalse(self.manager.has_perm("security.view_audit_log"))

    def test_application_page_requires_permission_and_lists_only_own_requests(self):
        own_request = self.submit()
        self.submit(applicant=self.other_applicant, board=self.other_board)
        url = reverse("boards:access-requests")

        self.client.force_login(self.applicant)
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(response.context["access_requests"], [own_request])

        submitted = self.client.post(
            url,
            {
                "board": self.other_board.pk,
                "requested_role": BoardMembership.Role.REVIEWER,
                "reason": "Review music posts",
            },
        )
        self.assertRedirects(submitted, url)
        self.assertTrue(
            BoardAccessRequest.objects.filter(
                applicant=self.applicant,
                board=self.other_board,
                requested_role=BoardMembership.Role.REVIEWER,
                status=BoardAccessRequest.Status.PENDING,
            ).exists()
        )

        self.client.force_login(self.manager)
        denied = self.client.get(url)
        self.assertEqual(denied.status_code, 403)

    def test_dashboard_review_queryset_is_scoped_to_managers_board(self):
        own_request = self.submit()
        self.submit(applicant=self.other_applicant, board=self.other_board)
        request = RequestFactory().get("/dashboard/boards/boardaccessrequest/")
        request.user = self.manager
        model_admin = DashboardBoardAccessRequestAdmin(
            BoardAccessRequest,
            AdminSite(),
        )

        self.assertQuerySetEqual(model_admin.get_queryset(request), [own_request])
