"""Security and lifecycle contracts for the Devenir Membership Dashboard."""

import base64
import os
from unittest.mock import patch

import pyotp
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.authn.mfa_services import (
    confirm_totp_enrollment,
    start_totp_enrollment,
)
from accounts.authn.mfa_session import (
    DASHBOARD_REMEMBER_KEY,
    PRIVILEGED_KEY,
    mark_privileged_session,
)
from accounts.models import MfaTotpDevice, MyUser
from boards.membership_step_up import (
    MembershipStepUpError,
    consume_membership_step_up,
    issue_membership_step_up,
)
from boards.models import (
    Board,
    BoardAccessRequest,
    BoardMembership,
    BoardMembershipEvent,
)
from boards.services import (
    MEMBERSHIP_ACTION_GRANT,
    membership_step_up_target,
)


def _encoded_key():
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


@override_settings(
    MFA_TOTP_KEYRING={"test-v1": _encoded_key()},
    MFA_TOTP_ACTIVE_KEY_ID="test-v1",
    MFA_TOTP_ISSUER="PowerAdapter Membership Test",
    MFA_TOTP_BINDING_TTL_SECONDS=600,
    MFA_TOTP_VALID_WINDOW=1,
    MFA_RECOVERY_CODE_COUNT=10,
    MFA_ENFORCEMENT_ENABLED=False,
    MFA_CHALLENGE_TTL_SECONDS=300,
    MFA_CHALLENGE_MAX_ATTEMPTS=5,
    MFA_CHALLENGE_COOLDOWN_SECONDS=900,
    MFA_PRIVILEGED_SESSION_TTL_SECONDS=900,
    MFA_DASHBOARD_REMEMBER_TTL_SECONDS=7 * 24 * 60 * 60,
    MEMBERSHIP_STEP_UP_TTL_SECONDS=300,
    LOG_HMAC_KEY=os.urandom(32),
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "sessions": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    },
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class DashboardMembershipTest(TestCase):
    password = "test-only-password"

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.operator = MyUser.objects.create_user(
            email="operator@example.test",
            username="membership_operator",
            password=self.password,
            is_active=True,
            is_dashboard_user=True,
        )
        permission = Permission.objects.get(
            content_type__app_label="boards",
            codename="manage_all_board_memberships",
        )
        self.operator.user_permissions.add(permission)
        enrollment = start_totp_enrollment(
            user=self.operator,
            actor=self.operator,
        )
        self.totp = pyotp.parse_uri(enrollment.provisioning_uri)
        confirm_totp_enrollment(
            user=self.operator,
            actor=self.operator,
            code=self.totp.now(),
        )
        self.device = MfaTotpDevice.objects.get(user=self.operator)
        self.board = Board.objects.create(slug="coding", name="Coding")
        self.member = MyUser.objects.create_user(
            email="member@example.test",
            username="member",
            password=self.password,
            is_active=True,
        )
        self._login_with_privileged_session()

    def _login_with_privileged_session(self):
        self.client.force_login(self.operator)
        request = self.factory.get("/dashboard/memberships/")
        request.user = self.operator
        request.session = self.client.session
        mark_privileged_session(request, self.device)
        request.session.save()

    def _fresh_step_and_code(self):
        self.device.refresh_from_db()
        step = (
            self.device.last_accepted_step
            or self.totp.timecode(timezone.now())
        ) + 1
        return step, self.totp.generate_otp(step)

    def _remember_dashboard_without_fresh_privilege(self):
        request = self.factory.get("/dashboard/memberships/")
        request.user = self.operator
        request.session = self.client.session
        mark_privileged_session(
            request,
            self.device,
            remember_dashboard=True,
        )
        request.session.pop(PRIVILEGED_KEY, None)
        request.session.save()

    def _post_with_fresh_code(self, url, data):
        step, code = self._fresh_step_and_code()
        with patch(
            "accounts.authn.mfa_services._matching_step",
            return_value=step,
        ):
            return self.client.post(url, {**data, "code": code})

    def _request_for_capability(self):
        request = self.factory.post("/dashboard/memberships/grant/")
        request.user = self.operator
        request.session = self.client.session
        return request

    def _create_event(self, membership, *, reason="Lifecycle reason"):
        return BoardMembershipEvent.objects.create(
            membership=membership,
            board=membership.board,
            user=membership.user,
            actor=self.operator,
            event_type=BoardMembershipEvent.EventType.GRANTED,
            source=BoardMembershipEvent.Source.DASHBOARD,
            previous_role="",
            new_role=membership.role,
            previous_is_active=None,
            new_is_active=membership.is_active,
            reason=reason,
            board_id_snapshot=membership.board_id,
            board_slug_snapshot=membership.board.slug,
            user_id_snapshot=membership.user_id,
            username_snapshot=membership.user.username,
            actor_id_snapshot=self.operator.pk,
            actor_username_snapshot=self.operator.username,
        )

    def _clear_permission_cache(self):
        for name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            self.operator.__dict__.pop(name, None)

    def test_list_requires_dashboard_permission_and_privileged_session(self):
        url = reverse("board-dashboard:memberships")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        self.operator.user_permissions.clear()
        self._clear_permission_cache()
        self.assertEqual(self.client.get(url).status_code, 403)

        self.operator.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="boards",
                codename="manage_all_board_memberships",
            )
        )
        self._clear_permission_cache()
        session = self.client.session
        session.pop(PRIVILEGED_KEY, None)
        session.save()
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_dashboard_remembered_grant_allows_list_and_fresh_operation_step_up(self):
        self._remember_dashboard_without_fresh_privilege()
        self.assertIn(DASHBOARD_REMEMBER_KEY, self.client.session)
        self.assertEqual(
            self.client.get(reverse("board-dashboard:memberships")).status_code,
            200,
        )

        step, code = self._fresh_step_and_code()
        with patch(
            "accounts.authn.mfa_services._matching_step",
            return_value=step,
        ):
            capability = issue_membership_step_up(
                request=self._request_for_capability(),
                action=MEMBERSHIP_ACTION_GRANT,
                target=membership_step_up_target(
                    action=MEMBERSHIP_ACTION_GRANT,
                    board_id=self.board.pk,
                    user_id=self.member.pk,
                    extra=BoardMembership.Role.EDITOR,
                ),
                code=code,
            )
        self.assertTrue(capability.token)

    def test_direct_grant_requires_fresh_totp_and_records_dashboard_event(self):
        response = self._post_with_fresh_code(
            reverse("board-dashboard:membership-grant"),
            {
                "board": self.board.pk,
                "user": self.member.pk,
                "role": BoardMembership.Role.EDITOR,
                "reason": "Initial editorial assignment",
            },
        )
        self.assertRedirects(response, reverse("board-dashboard:memberships"))
        membership = BoardMembership.objects.get(
            board=self.board,
            user=self.member,
        )
        self.assertEqual(membership.role, BoardMembership.Role.EDITOR)
        event = BoardMembershipEvent.objects.get(membership=membership)
        self.assertEqual(event.event_type, BoardMembershipEvent.EventType.GRANTED)
        self.assertEqual(event.source, BoardMembershipEvent.Source.DASHBOARD)
        self.assertEqual(event.actor, self.operator)

    def test_pending_request_blocks_direct_grant(self):
        BoardAccessRequest.objects.create(
            board=self.board,
            applicant=self.member,
            requested_role=BoardMembership.Role.CONTRIBUTOR,
            reason="Pending request",
        )
        response = self._post_with_fresh_code(
            reverse("board-dashboard:membership-grant"),
            {
                "board": self.board.pk,
                "user": self.member.pk,
                "role": BoardMembership.Role.EDITOR,
                "reason": "Must not bypass review",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "待审核")
        self.assertFalse(BoardMembership.objects.exists())
        self.assertFalse(BoardMembershipEvent.objects.exists())

    def test_invalid_totp_does_not_mutate_membership(self):
        with patch(
            "accounts.authn.mfa_services._matching_step",
            return_value=None,
        ):
            response = self.client.post(
                reverse("board-dashboard:membership-grant"),
                {
                    "board": self.board.pk,
                    "user": self.member.pk,
                    "role": BoardMembership.Role.EDITOR,
                    "reason": "Must not pass",
                    "code": "000000",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "动态验证码无效")
        self.assertFalse(BoardMembership.objects.exists())

    def test_role_deactivate_and_reactivate_follow_lifecycle(self):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.member,
            role=BoardMembership.Role.CONTRIBUTOR,
            created_by=self.operator,
        )
        role_response = self._post_with_fresh_code(
            reverse("board-dashboard:membership-role", args=(membership.pk,)),
            {
                "role": BoardMembership.Role.EDITOR,
                "reason": "Expanded editorial responsibility",
            },
        )
        self.assertRedirects(
            role_response,
            reverse("board-dashboard:memberships"),
        )

        deactivate_response = self._post_with_fresh_code(
            reverse(
                "board-dashboard:membership-deactivate",
                args=(membership.pk,),
            ),
            {"reason": "Temporary access removal"},
        )
        self.assertRedirects(
            deactivate_response,
            reverse("board-dashboard:memberships"),
        )

        reactivate_response = self._post_with_fresh_code(
            reverse(
                "board-dashboard:membership-reactivate",
                args=(membership.pk,),
            ),
            {
                "role": BoardMembership.Role.REVIEWER,
                "reason": "Return with reduced scope",
            },
        )
        self.assertRedirects(
            reactivate_response,
            reverse("board-dashboard:memberships"),
        )
        membership.refresh_from_db()
        self.assertTrue(membership.is_active)
        self.assertEqual(membership.role, BoardMembership.Role.REVIEWER)
        self.assertQuerySetEqual(
            BoardMembershipEvent.objects.values_list("event_type", flat=True),
            [
                BoardMembershipEvent.EventType.ROLE_CHANGED,
                BoardMembershipEvent.EventType.DEACTIVATED,
                BoardMembershipEvent.EventType.REACTIVATED,
            ],
            ordered=False,
        )

    def test_step_up_capability_is_target_bound_and_one_shot(self):
        request = self._request_for_capability()
        target = membership_step_up_target(
            action=MEMBERSHIP_ACTION_GRANT,
            board_id=self.board.pk,
            user_id=self.member.pk,
        )
        step, code = self._fresh_step_and_code()
        with patch(
            "accounts.authn.mfa_services._matching_step",
            return_value=step,
        ):
            capability = issue_membership_step_up(
                request=request,
                action=MEMBERSHIP_ACTION_GRANT,
                target=target,
                code=code,
            )

        with self.assertRaises(MembershipStepUpError) as mismatch:
            consume_membership_step_up(
                request=request,
                capability=capability,
                actor=self.operator,
                action=MEMBERSHIP_ACTION_GRANT,
                target=f"{target}:different",
            )
        self.assertEqual(mismatch.exception.reason, "binding_mismatch")

        self.assertTrue(
            consume_membership_step_up(
                request=request,
                capability=capability,
                actor=self.operator,
                action=MEMBERSHIP_ACTION_GRANT,
                target=target,
            )
        )
        with self.assertRaises(MembershipStepUpError) as replay:
            consume_membership_step_up(
                request=request,
                capability=capability,
                actor=self.operator,
                action=MEMBERSHIP_ACTION_GRANT,
                target=target,
            )
        self.assertEqual(replay.exception.reason, "already_consumed")

    def test_last_manager_cannot_be_deactivated(self):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.member,
            role=BoardMembership.Role.MANAGER,
            created_by=self.operator,
        )
        response = self._post_with_fresh_code(
            reverse(
                "board-dashboard:membership-deactivate",
                args=(membership.pk,),
            ),
            {"reason": "Invalid last-manager removal"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "最后一名 Manager")
        membership.refresh_from_db()
        self.assertTrue(membership.is_active)
        self.assertFalse(BoardMembershipEvent.objects.exists())

    def test_last_manager_cannot_be_demoted_through_role_form(self):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.member,
            role=BoardMembership.Role.MANAGER,
            created_by=self.operator,
        )
        response = self._post_with_fresh_code(
            reverse("board-dashboard:membership-role", args=(membership.pk,)),
            {
                "role": BoardMembership.Role.EDITOR,
                "reason": "Invalid last-manager demotion",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "最后一名 Manager")
        membership.refresh_from_db()
        self.assertEqual(membership.role, BoardMembership.Role.MANAGER)
        self.assertTrue(membership.is_active)
        self.assertFalse(BoardMembershipEvent.objects.exists())

    def test_manager_transfer_is_atomic_and_records_both_sides(self):
        old_manager = BoardMembership.objects.create(
            board=self.board,
            user=self.member,
            role=BoardMembership.Role.MANAGER,
            created_by=self.operator,
        )
        replacement_user = MyUser.objects.create_user(
            email="replacement@example.test",
            username="replacement",
            password=self.password,
            is_active=True,
        )
        replacement = BoardMembership.objects.create(
            board=self.board,
            user=replacement_user,
            role=BoardMembership.Role.EDITOR,
            created_by=self.operator,
        )
        response = self._post_with_fresh_code(
            reverse(
                "board-dashboard:manager-transfer",
                args=(old_manager.pk,),
            ),
            {
                "target_user": replacement_user.pk,
                "old_disposition": BoardMembership.Role.REVIEWER,
                "reason": "Scheduled manager rotation",
            },
        )
        self.assertRedirects(response, reverse("board-dashboard:memberships"))
        old_manager.refresh_from_db()
        replacement.refresh_from_db()
        self.assertEqual(old_manager.role, BoardMembership.Role.REVIEWER)
        self.assertTrue(old_manager.is_active)
        self.assertEqual(replacement.role, BoardMembership.Role.MANAGER)
        self.assertTrue(replacement.is_active)
        events = BoardMembershipEvent.objects.filter(
            event_type=BoardMembershipEvent.EventType.MANAGER_TRANSFERRED,
        )
        self.assertEqual(events.count(), 2)

    def test_list_filters_memberships_without_mutating_them(self):
        other_board = Board.objects.create(slug="music", name="Music")
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.member,
            role=BoardMembership.Role.REVIEWER,
            created_by=self.operator,
        )
        other_user = MyUser.objects.create_user(
            email="other@example.test",
            username="other",
            password=self.password,
            is_active=True,
        )
        BoardMembership.objects.create(
            board=other_board,
            user=other_user,
            role=BoardMembership.Role.CONTRIBUTOR,
            created_by=self.operator,
        )
        response = self.client.get(
            reverse("board-dashboard:memberships"),
            {"board": self.board.pk, "role": "reviewer", "q": "member"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(response.context["memberships"], [membership])

    def test_global_event_history_filters_snapshot_fields(self):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.member,
            role=BoardMembership.Role.REVIEWER,
            created_by=self.operator,
        )
        event = self._create_event(membership, reason="Reviewer rotation")
        membership.delete()

        response = self.client.get(
            reverse("board-dashboard:membership-events"),
            {
                "q": "rotation",
                "board": self.board.slug,
                "event_type": BoardMembershipEvent.EventType.GRANTED,
                "source": BoardMembershipEvent.Source.DASHBOARD,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(response.context["events"], [event])
        self.assertContains(response, self.member.username)
        self.assertContains(response, "Reviewer rotation")

    def test_membership_event_history_is_scoped_to_selected_membership(self):
        membership = BoardMembership.objects.create(
            board=self.board,
            user=self.member,
            role=BoardMembership.Role.EDITOR,
            created_by=self.operator,
        )
        expected = self._create_event(membership)
        other_user = MyUser.objects.create_user(
            email="history-other@example.test",
            username="history-other",
            password=self.password,
            is_active=True,
        )
        other_membership = BoardMembership.objects.create(
            board=self.board,
            user=other_user,
            role=BoardMembership.Role.CONTRIBUTOR,
            created_by=self.operator,
        )
        self._create_event(other_membership)

        response = self.client.get(
            reverse(
                "board-dashboard:membership-event-history",
                args=(membership.pk,),
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["membership"], membership)
        self.assertQuerySetEqual(response.context["events"], [expected])
