import re
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from PowerAdapterBlogs.base_admin import has_dashboard_access
from accounts.models import MyUser
from accounts.services import (
    EMAIL_PURPOSE_BOARD_ACCESS,
    mark_email_verification_verified,
)
from boards.admin import DashboardBoardAccessRequestAdmin
from boards.models import (
    Board,
    BoardAccessRequest,
    BoardMembership,
    BoardMembershipEvent,
)
from boards.services import (
    approve_board_access_request,
    reject_board_access_request,
    submit_board_access_request,
    withdraw_board_membership,
)


class BoardAccessRequestTest(TestCase):
    password = "test-password-2026"

    def setUp(self):
        cache.clear()
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

    def grant_board_email_verification(self):
        request = RequestFactory().get("/boards/access/")
        request.user = self.applicant
        request.session = self.client.session
        mark_email_verification_verified(request, EMAIL_PURPOSE_BOARD_ACCESS)
        request.session.save()

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
        event = BoardMembershipEvent.objects.get(membership=membership)
        self.assertEqual(event.event_type, BoardMembershipEvent.EventType.GRANTED)
        self.assertEqual(event.source, BoardMembershipEvent.Source.ACCESS_REQUEST)
        self.assertEqual(event.access_request, access_request)
        self.assertIsNone(event.previous_is_active)
        self.assertTrue(event.new_is_active)
        self.assertEqual(event.board_slug_snapshot, self.board.slug)
        self.assertEqual(event.username_snapshot, self.applicant.username)

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
        event = BoardMembershipEvent.objects.get(membership=membership)
        self.assertEqual(
            event.event_type,
            BoardMembershipEvent.EventType.REACTIVATED,
        )
        self.assertEqual(event.previous_role, BoardMembership.Role.CONTRIBUTOR)
        self.assertEqual(event.new_role, BoardMembership.Role.EDITOR)
        self.assertFalse(event.previous_is_active)
        self.assertTrue(event.new_is_active)
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

    def test_approval_rejects_no_op_if_membership_changed_while_pending(self):
        access_request = self.submit(role=BoardMembership.Role.CONTRIBUTOR)
        BoardMembership.objects.create(
            board=self.board,
            user=self.applicant,
            role=BoardMembership.Role.CONTRIBUTOR,
            created_by=self.superuser,
        )

        with self.assertRaisesMessage(ValidationError, "没有发生变化"):
            approve_board_access_request(
                access_request=access_request,
                actor=self.manager,
            )

        access_request.refresh_from_db()
        self.assertEqual(access_request.status, BoardAccessRequest.Status.PENDING)
        self.assertFalse(BoardMembershipEvent.objects.exists())

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

    @patch("boards.services.BoardMembershipEvent.objects.create")
    def test_membership_event_failure_rolls_back_approval(self, create_event):
        create_event.side_effect = RuntimeError("event write failed")
        access_request = self.submit()

        with self.assertRaises(RuntimeError):
            approve_board_access_request(
                access_request=access_request,
                actor=self.manager,
            )

        access_request.refresh_from_db()
        self.assertEqual(access_request.status, BoardAccessRequest.Status.PENDING)
        self.assertFalse(
            BoardMembership.objects.filter(
                board=self.board,
                user=self.applicant,
            ).exists()
        )

    def test_manager_membership_does_not_grant_dashboard_shell_or_global_permissions(self):
        self.assertFalse(has_dashboard_access(self.manager))
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

        self.grant_board_email_verification()
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

    def test_application_page_lists_current_active_memberships(self):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.applicant,
            role=BoardMembership.Role.EDITOR,
            created_by=self.superuser,
        )
        BoardMembership.objects.create(
            board=self.other_board,
            user=self.applicant,
            role=BoardMembership.Role.CONTRIBUTOR,
            is_active=False,
            created_by=self.superuser,
        )
        self.client.force_login(self.applicant)

        response = self.client.get(reverse("boards:access-requests"))

        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(response.context["active_memberships"], [membership])
        self.assertContains(response, "CURRENT ACCESS / 已获得权限")
        self.assertContains(response, self.board.name)
        self.assertContains(response, "退出板块")

    def test_membership_withdrawal_requires_email_verification(self):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.applicant,
            role=BoardMembership.Role.EDITOR,
            created_by=self.superuser,
        )
        self.client.force_login(self.applicant)

        response = self.client.post(
            reverse("boards:withdraw-membership", args=(membership.pk,))
        )

        self.assertRedirects(
            response,
            reverse("accounts:board-access-email-verify"),
        )
        membership.refresh_from_db()
        self.assertTrue(membership.is_active)

    @patch("boards.services._audit_membership_event")
    def test_member_can_withdraw_own_membership_after_email_verification(
        self,
        audit_event,
    ):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.applicant,
            role=BoardMembership.Role.REVIEWER,
            created_by=self.superuser,
        )
        self.client.force_login(self.applicant)
        self.grant_board_email_verification()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("boards:withdraw-membership", args=(membership.pk,)),
                follow=True,
            )

        membership.refresh_from_db()
        self.assertFalse(membership.is_active)
        self.assertContains(response, f"已退出 {self.board.name} 板块")
        event = BoardMembershipEvent.objects.get(membership=membership)
        self.assertEqual(
            event.event_type,
            BoardMembershipEvent.EventType.DEACTIVATED,
        )
        self.assertEqual(event.source, BoardMembershipEvent.Source.SELF_SERVICE)
        self.assertTrue(event.previous_is_active)
        self.assertFalse(event.new_is_active)
        audit_event.assert_called_once_with(event.pk)

    def test_member_cannot_withdraw_another_users_or_manager_membership(self):
        another_membership = BoardMembership.objects.create(
            board=self.board,
            user=self.applicant,
            role=BoardMembership.Role.EDITOR,
            created_by=self.superuser,
        )
        manager_membership = BoardMembership.objects.get(
            board=self.board,
            user=self.manager,
        )

        with self.assertRaises(PermissionDenied):
            withdraw_board_membership(
                membership=another_membership,
                actor=self.other_applicant,
            )
        with self.assertRaisesMessage(PermissionDenied, "Manager 不能自助退出"):
            withdraw_board_membership(
                membership=manager_membership,
                actor=self.manager,
            )

    def test_member_cannot_withdraw_while_same_board_request_is_pending(self):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.applicant,
            role=BoardMembership.Role.EDITOR,
            created_by=self.superuser,
        )
        self.submit(role=BoardMembership.Role.REVIEWER)

        with self.assertRaisesMessage(ValidationError, "仍有待审核申请"):
            withdraw_board_membership(
                membership=membership,
                actor=self.applicant,
            )

        membership.refresh_from_db()
        self.assertTrue(membership.is_active)
        self.assertFalse(BoardMembershipEvent.objects.exists())

    def test_successful_application_shows_one_time_devenir_dialog(self):
        url = reverse("boards:access-requests")
        self.client.force_login(self.applicant)
        self.grant_board_email_verification()

        response = self.client.post(
            url,
            {
                "board": self.board.pk,
                "requested_role": BoardMembership.Role.CONTRIBUTOR,
                "reason": "I can help.",
            },
            follow=True,
        )

        self.assertContains(response, "申请已提交")
        self.assertContains(response, "主动联系管理员")
        self.assertContains(response, "access-success-dialog")
        refreshed = self.client.get(url)
        self.assertNotContains(refreshed, "access-success-dialog")
        self.assertContains(refreshed, "需要短时邮箱确认")

    def test_direct_application_post_requires_email_verification(self):
        url = reverse("boards:access-requests")
        self.client.force_login(self.applicant)

        response = self.client.post(
            url,
            {
                "board": self.board.pk,
                "requested_role": BoardMembership.Role.CONTRIBUTOR,
                "reason": "I can help.",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:board-access-email-verify"),
        )
        self.assertFalse(
            BoardAccessRequest.objects.filter(applicant=self.applicant).exists()
        )

    def test_board_email_challenge_requires_application_permission(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("accounts:board-access-email-verify"))

        self.assertEqual(response.status_code, 403)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        PASSWORD_EMAIL_SEND_COOLDOWN_SECONDS=0,
    )
    def test_board_email_challenge_grants_one_application(self):
        access_url = reverse("boards:access-requests")
        verify_url = reverse("accounts:board-access-email-verify")
        self.client.force_login(self.applicant)

        gated = self.client.get(access_url)
        self.assertContains(gated, "需要短时邮箱确认")
        self.client.post(verify_url, {"action": "send"})
        self.assertEqual(mail.outbox[-1].subject, "PowerAdapter 板块权限申请验证码")
        code_match = re.search(r"(?<!\d)(\d{6})(?!\d)", mail.outbox[-1].body)
        self.assertIsNotNone(code_match)

        verified = self.client.post(verify_url, {"code": code_match.group(1)})
        self.assertRedirects(verified, access_url)
        self.assertContains(self.client.get(access_url), "MAIL VERIFIED")

        submitted = self.client.post(
            access_url,
            {
                "board": self.board.pk,
                "requested_role": BoardMembership.Role.CONTRIBUTOR,
                "reason": "I can help.",
            },
            follow=True,
        )
        self.assertContains(submitted, "申请已提交")
        self.assertContains(submitted, "需要短时邮箱确认")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        PASSWORD_EMAIL_SEND_COOLDOWN_SECONDS=0,
    )
    def test_password_code_cannot_authorize_board_application(self):
        self.client.force_login(self.applicant)
        self.client.post(
            reverse("accounts:password-email-verify"),
            {"action": "send"},
        )
        code_match = re.search(r"(?<!\d)(\d{6})(?!\d)", mail.outbox[-1].body)
        self.assertIsNotNone(code_match)

        response = self.client.post(
            reverse("accounts:board-access-email-verify"),
            {"code": code_match.group(1)},
        )

        self.assertContains(response, "验证码不存在或已过期")
        self.assertContains(
            self.client.get(reverse("boards:access-requests")),
            "需要短时邮箱确认",
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        PASSWORD_EMAIL_SEND_COOLDOWN_SECONDS=0,
        PASSWORD_EMAIL_MAX_SENDS=1,
    )
    def test_email_send_limit_is_shared_across_purposes(self):
        self.client.force_login(self.applicant)
        self.client.post(
            reverse("accounts:password-email-verify"),
            {"action": "send"},
        )

        response = self.client.post(
            reverse("accounts:board-access-email-verify"),
            {"action": "send"},
            follow=True,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(response, "本小时发送次数已用完")

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
