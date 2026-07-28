from datetime import timedelta

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.authn.mfa_session import mfa_required_for_user
from accounts.models import AccountInvitation, MyUser
from boards.models import Board, BoardAccessRequest, BoardMembership
from PowerAdapterBlogs.base_admin import has_dashboard_access


class ModerationBoundaryTest(TestCase):
    password = "test-password"

    def create_user(self, username, **extra):
        return MyUser.objects.create_user(
            email=f"{username}@example.test",
            username=username,
            password=self.password,
            is_active=True,
            **extra,
        )

    def test_user_manager_uses_review_center_without_dashboard_access(self):
        manager = self.create_user("user-manager")
        manager.user_permissions.add(
            Permission.objects.get(codename="manage_user_accounts")
        )
        self.client.force_login(manager)

        self.assertFalse(has_dashboard_access(manager))
        self.assertEqual(self.client.get(reverse("cus_admin:index")).status_code, 302)
        self.assertEqual(self.client.get(reverse("moderation:hub")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("moderation:accounts")).status_code,
            200,
        )

    def test_account_reviewer_cannot_activate_unaccepted_invitation(self):
        manager = self.create_user("account-reviewer")
        manager.user_permissions.add(
            Permission.objects.get(codename="manage_user_accounts")
        )
        target = self.create_user("invited-target")
        target.is_active = False
        target.save(update_fields=("is_active",))
        AccountInvitation.objects.create(
            user=target,
            created_by=manager,
            token_digest="a" * 64,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.client.force_login(manager)
        response = self.client.post(
            reverse("moderation:accounts"),
            {"user_id": target.pk, "action": "activate"},
            follow=True,
        )

        target.refresh_from_db()
        self.assertFalse(target.is_active)
        self.assertContains(response, "不能绕过邀请流程")

    def test_dashboard_user_requires_mfa_but_plain_user_does_not(self):
        dashboard_user = self.create_user(
            "dashboard-user",
            is_dashboard_user=True,
        )
        plain_user = self.create_user("plain-user")

        self.assertTrue(has_dashboard_access(dashboard_user))
        self.assertTrue(mfa_required_for_user(dashboard_user))
        self.assertFalse(mfa_required_for_user(plain_user))

    def test_board_manager_reviews_membership_without_dashboard_access(self):
        manager = self.create_user("board-manager")
        applicant = self.create_user("board-applicant")
        board = Board.objects.create(slug="coding-review", name="Coding Review")
        BoardMembership.objects.create(
            board=board,
            user=manager,
            role=BoardMembership.Role.MANAGER,
            created_by=manager,
        )
        access_request = BoardAccessRequest.objects.create(
            board=board,
            applicant=applicant,
            requested_role=BoardMembership.Role.EDITOR,
            reason="Help edit this board",
        )
        self.client.force_login(manager)

        self.assertFalse(has_dashboard_access(manager))
        self.assertEqual(self.client.get(reverse("moderation:boards")).status_code, 200)
        response = self.client.post(
            reverse("moderation:boards"),
            {"request_id": access_request.pk, "action": "approve"},
        )

        self.assertRedirects(response, reverse("moderation:boards"))
        access_request.refresh_from_db()
        self.assertEqual(access_request.status, BoardAccessRequest.Status.APPROVED)
        self.assertTrue(
            BoardMembership.objects.filter(
                board=board,
                user=applicant,
                role=BoardMembership.Role.EDITOR,
                is_active=True,
            ).exists()
        )
