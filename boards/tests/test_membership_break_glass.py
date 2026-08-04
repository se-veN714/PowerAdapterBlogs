"""Full-verification contracts for the super-admin Membership exception."""

import base64
import os
from datetime import timedelta
from unittest.mock import patch

import pyotp
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.authn.mfa_services import (
    confirm_totp_enrollment,
    start_totp_enrollment,
)
from accounts.authn.mtls_services import bind_client_certificate
from accounts.models import MfaTotpDevice, MyUser
from boards.models import Board, BoardMembership, BoardMembershipEvent
from boards.services import membership_break_glass_confirmation


def _encoded_key():
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


BREAK_GLASS_SETTINGS = {
    "ALLOWED_HOSTS": ["admin.example.test", "testserver"],
    "MTLS_ENFORCEMENT_ENABLED": True,
    "MTLS_ADMIN_HOST": "admin.example.test",
    "MTLS_TRUSTED_PROXY_NETWORKS": ("127.0.0.1/32",),
    "MTLS_PROXY_AUTH_SECRET": "test-only-proxy-secret-at-least-32-bytes",
    "MTLS_CERTIFICATE_PROFILE": "standard-tls",
    "MFA_TOTP_KEYRING": {"test-v1": _encoded_key()},
    "MFA_TOTP_ACTIVE_KEY_ID": "test-v1",
    "MFA_TOTP_ISSUER": "PowerAdapter Break Glass Test",
    "MFA_TOTP_BINDING_TTL_SECONDS": 600,
    "MFA_TOTP_VALID_WINDOW": 1,
    "MFA_RECOVERY_CODE_COUNT": 10,
    "MFA_ENFORCEMENT_ENABLED": True,
    "MFA_CHALLENGE_TTL_SECONDS": 300,
    "MFA_CHALLENGE_MAX_ATTEMPTS": 5,
    "MFA_CHALLENGE_COOLDOWN_SECONDS": 900,
    "MFA_PRIVILEGED_SESSION_TTL_SECONDS": 900,
    "MEMBERSHIP_STEP_UP_TTL_SECONDS": 300,
    "LOG_HMAC_KEY": os.urandom(32),
    "PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"],
    "CACHES": {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "sessions": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    },
}


@override_settings(**BREAK_GLASS_SETTINGS)
class MembershipBreakGlassTest(TestCase):
    password = "test-only-password"

    def setUp(self):
        cache.clear()
        self.user = MyUser.objects.create_superuser(
            email="break-glass@example.test",
            username="break-glass-root",
            password=self.password,
        )
        enrollment = start_totp_enrollment(user=self.user, actor=self.user)
        self.totp = pyotp.parse_uri(enrollment.provisioning_uri)
        confirm_totp_enrollment(
            user=self.user,
            actor=self.user,
            code=self.totp.now(),
        )
        self.device = MfaTotpDevice.objects.get(user=self.user)
        self.binding = bind_client_certificate(
            user=self.user,
            actor=self.user,
            serial_number="B100",
            issuer_dn="CN=PowerAdapter Client CA,O=PowerAdapter",
            subject_dn="CN=break-glass-root,O=PowerAdapter",
            certificate_profile="standard-tls",
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.headers = {
            "HTTP_HOST": "admin.example.test",
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_X_PA_PROXY_AUTH": BREAK_GLASS_SETTINGS[
                "MTLS_PROXY_AUTH_SECRET"
            ],
            "HTTP_X_PA_MTLS_VERIFY": "SUCCESS",
            "HTTP_X_PA_MTLS_SERIAL": self.binding.serial_number,
            "HTTP_X_PA_MTLS_ISSUER_DN": self.binding.issuer_dn,
            "HTTP_X_PA_MTLS_SUBJECT_DN": self.binding.subject_dn,
            "HTTP_X_PA_MTLS_PROFILE": "standard-tls",
        }
        self.board = Board.objects.create(slug="orphan-risk", name="Orphan Risk")
        self.manager_user = MyUser.objects.create_user(
            email="last-manager@example.test",
            username="last-manager",
            password=self.password,
            is_active=True,
        )
        self.membership = BoardMembership.objects.create(
            board=self.board,
            user=self.manager_user,
            role=BoardMembership.Role.MANAGER,
            created_by=self.user,
        )
        self.url = reverse(
            "admin:boards_boardmembership_break_glass_deactivate",
            args=(self.membership.pk,),
        )

    def _fresh_step_and_code(self):
        self.device.refresh_from_db()
        step = (
            self.device.last_accepted_step
            or self.totp.timecode(timezone.now())
        ) + 1
        return step, self.totp.generate_otp(step)

    def _full_login(self):
        self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.username,
                "password": self.password,
                "next": self.url,
            },
            **self.headers,
        )
        step, code = self._fresh_step_and_code()
        with patch(
            "accounts.authn.mfa_services._matching_step",
            return_value=step,
        ):
            response = self.client.post(
                reverse("accounts:mfa-challenge"),
                {"action": "totp", "code": code},
                **self.headers,
            )
        self.assertEqual(response.status_code, 302)

    def _break_glass_post(self, *, confirmation=None):
        step, code = self._fresh_step_and_code()
        with patch(
            "accounts.authn.mfa_services._matching_step",
            return_value=step,
        ):
            return self.client.post(
                self.url,
                {
                    "reason": "No replacement exists after incident response",
                    "confirmation": confirmation
                    or membership_break_glass_confirmation(self.membership),
                    "code": code,
                },
                **self.headers,
            )

    def test_full_verification_can_deactivate_only_last_manager(self):
        self._full_login()

        response = self._break_glass_post()

        self.assertRedirects(
            response,
            reverse("admin:boards_boardmembership_changelist"),
            fetch_redirect_response=False,
        )
        self.membership.refresh_from_db()
        self.assertFalse(self.membership.is_active)
        event = BoardMembershipEvent.objects.get(membership=self.membership)
        self.assertEqual(event.source, BoardMembershipEvent.Source.SUPER_ADMIN)
        self.assertEqual(
            event.event_type,
            BoardMembershipEvent.EventType.DEACTIVATED,
        )

    def test_wrong_confirmation_fails_closed(self):
        self._full_login()

        response = self._break_glass_post(confirmation="DEACTIVATE WRONG TARGET")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "确认短语不匹配")
        self.membership.refresh_from_db()
        self.assertTrue(self.membership.is_active)
        self.assertFalse(BoardMembershipEvent.objects.exists())

    def test_existing_second_manager_requires_normal_dashboard_path(self):
        second_user = MyUser.objects.create_user(
            email="second-manager@example.test",
            username="second-manager",
            password=self.password,
            is_active=True,
        )
        BoardMembership.objects.create(
            board=self.board,
            user=second_user,
            role=BoardMembership.Role.MANAGER,
            created_by=self.user,
        )
        self._full_login()

        response = self._break_glass_post()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "仍有其他 Manager")
        self.membership.refresh_from_db()
        self.assertTrue(self.membership.is_active)

    def test_missing_presented_certificate_is_rejected(self):
        self._full_login()

        response = self.client.get(
            self.url,
            HTTP_HOST="admin.example.test",
        )

        self.assertEqual(response.status_code, 403)
