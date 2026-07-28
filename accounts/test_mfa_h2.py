import base64
import os
from io import StringIO
from datetime import timedelta
from unittest.mock import patch

import pyotp
from django.contrib.admin.models import LogEntry
from django.contrib.auth import SESSION_KEY
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .mfa_services import (
    MfaServiceError,
    confirm_totp_enrollment,
    start_totp_enrollment,
    verify_active_totp,
)
from .mfa_session import PENDING_KEY, PRIVILEGED_KEY, RECOVERY_KEY
from .models import MfaTotpDevice, MyUser


def _encoded_key():
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


@override_settings(
    MFA_TOTP_KEYRING={"test-v1": _encoded_key()},
    MFA_TOTP_ACTIVE_KEY_ID="test-v1",
    MFA_TOTP_ISSUER="PowerAdapter Test",
    MFA_TOTP_BINDING_TTL_SECONDS=600,
    MFA_TOTP_VALID_WINDOW=1,
    MFA_RECOVERY_CODE_COUNT=10,
    MFA_ENFORCEMENT_ENABLED=True,
    MFA_CHALLENGE_TTL_SECONDS=300,
    MFA_CHALLENGE_MAX_ATTEMPTS=5,
    MFA_CHALLENGE_COOLDOWN_SECONDS=900,
    MFA_PRIVILEGED_SESSION_TTL_SECONDS=900,
    LOG_HMAC_KEY=os.urandom(32),
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "sessions": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    },
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class H2PrivilegedAuthenticationTest(TestCase):
    password = "test-only-password"

    def setUp(self):
        cache.clear()
        self.user = MyUser.objects.create_superuser(
            email="h2-admin@example.test",
            username="h2_admin",
            password=self.password,
        )
        enrollment = start_totp_enrollment(user=self.user, actor=self.user)
        self.totp = pyotp.parse_uri(enrollment.provisioning_uri)
        confirmation = confirm_totp_enrollment(
            user=self.user,
            actor=self.user,
            code=self.totp.now(),
        )
        self.recovery_codes = confirmation.recovery_codes
        self.device = MfaTotpDevice.objects.get(user=self.user)

    def _begin_login(self, target=None):
        target = target or reverse("admin:index")
        return self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.username,
                "password": self.password,
                "next": target,
            },
        )

    def _fresh_step_and_code(self):
        self.device.refresh_from_db()
        next_step = (
            self.device.last_accepted_step or self.totp.timecode(timezone.now())
        ) + 1
        return next_step, self.totp.generate_otp(next_step)

    def _invalid_code(self):
        current_step = self.totp.timecode(timezone.now())
        accepted = {
            self.totp.generate_otp(current_step + offset) for offset in (-1, 0, 1)
        }
        return next(
            f"{candidate:06d}"
            for candidate in range(1_000_000)
            if f"{candidate:06d}" not in accepted
        )

    def _complete_challenge(self):
        self._begin_login()
        step, code = self._fresh_step_and_code()
        with patch("accounts.mfa_services._matching_step", return_value=step):
            return self.client.post(
                reverse("accounts:mfa-challenge"),
                {"action": "totp", "code": code},
            )

    def test_password_only_creates_pending_challenge_not_authenticated_session(self):
        response = self._begin_login()
        self.assertRedirects(response, reverse("accounts:mfa-challenge"))
        session = self.client.session
        self.assertNotIn(SESSION_KEY, session)
        self.assertIn(PENDING_KEY, session)
        pending = session[PENDING_KEY]
        self.assertEqual(pending["user_id"], self.user.pk)
        self.assertNotIn("password", str(pending).lower())

    def test_challenge_rejects_external_target_expiry_and_user_tampering(self):
        self._begin_login(target="https://evil.example/steal")
        session = self.client.session
        self.assertEqual(session[PENDING_KEY]["target"], reverse("cus_admin:index"))
        self.assertNotIn("evil.example", str(session[PENDING_KEY]))
        session[PENDING_KEY]["issued_at"] = (
            timezone.now() - timedelta(minutes=6)
        ).timestamp()
        session.save()
        self.assertRedirects(
            self.client.get(reverse("accounts:mfa-challenge")),
            reverse("accounts:login"),
        )
        self.assertNotIn(PENDING_KEY, self.client.session)

        self._begin_login()
        session = self.client.session
        session[PENDING_KEY]["user_id"] = 999999
        session.save()
        self.assertRedirects(
            self.client.get(reverse("accounts:mfa-challenge")),
            reverse("accounts:login"),
        )

    def test_fresh_totp_logs_in_and_issues_privileged_session(self):
        response = self._complete_challenge()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin:index"))
        session = self.client.session
        self.assertEqual(int(session[SESSION_KEY]), self.user.pk)
        self.assertIn(PRIVILEGED_KEY, session)
        self.assertNotIn(PENDING_KEY, session)
        admin_response = self.client.get(reverse("admin:index"))
        self.assertEqual(
            admin_response.status_code,
            200,
            msg=f"unexpected admin redirect: {admin_response.get('Location')}",
        )

    def test_same_totp_step_cannot_be_replayed(self):
        step, code = self._fresh_step_and_code()
        with patch("accounts.mfa_services._matching_step", return_value=step):
            verify_active_totp(user=self.user, actor=self.user, code=code)
            with self.assertRaises(MfaServiceError) as context:
                verify_active_totp(user=self.user, actor=self.user, code=code)
        self.assertEqual(context.exception.reason, "replayed_code")
        self.assertTrue(
            LogEntry.objects.filter(
                change_message__contains="reason=replayed_code"
            ).exists()
        )

    def test_fifth_failure_enters_shared_cooldown(self):
        self._begin_login()
        invalid_code = self._invalid_code()
        for attempt in range(5):
            response = self.client.post(
                reverse("accounts:mfa-challenge"),
                {"action": "totp", "code": invalid_code},
            )
            self.assertEqual(response.status_code, 429 if attempt == 4 else 400)
        locked = self.client.post(
            reverse("accounts:mfa-challenge"),
            {"action": "totp", "code": "111111"},
        )
        self.assertEqual(locked.status_code, 429)

    def test_admin_requires_current_privileged_session(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:index"))
        self.assertRedirects(response, reverse("accounts:mfa-challenge"))

        step, code = self._fresh_step_and_code()
        with patch("accounts.mfa_services._matching_step", return_value=step):
            response = self.client.post(
                reverse("accounts:mfa-challenge"),
                {"action": "totp", "code": code},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin:index"))
        admin_response = self.client.get(reverse("admin:index"))
        self.assertEqual(
            admin_response.status_code,
            200,
            msg=f"unexpected admin redirect: {admin_response.get('Location')}",
        )

    def test_expired_or_version_mismatched_privileged_session_is_rejected(self):
        self._complete_challenge()
        session = self.client.session
        session[PRIVILEGED_KEY]["verified_at"] = (
            timezone.now() - timedelta(minutes=16)
        ).timestamp()
        session.save()
        self.assertRedirects(
            self.client.get(reverse("admin:index")),
            reverse("accounts:mfa-challenge"),
        )

        self._complete_challenge()
        MfaTotpDevice.objects.filter(pk=self.device.pk).update(auth_version=2)
        self.assertRedirects(
            self.client.get(reverse("admin:index")),
            reverse("accounts:mfa-challenge"),
        )

    def test_recovery_code_only_enters_restricted_rebinding_state(self):
        self._begin_login()
        response = self.client.post(
            reverse("accounts:mfa-challenge"),
            {"action": "recovery", "recovery_code": self.recovery_codes[0]},
        )
        self.assertRedirects(response, reverse("accounts:mfa-settings"))
        session = self.client.session
        self.assertIn(SESSION_KEY, session)
        self.assertIn(RECOVERY_KEY, session)
        self.assertNotIn(PRIVILEGED_KEY, session)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, MfaTotpDevice.Status.REVOKED)
        self.assertRedirects(
            self.client.get(reverse("index")),
            reverse("accounts:mfa-settings"),
        )

    def test_recovery_rebind_clears_restriction_and_issues_privilege(self):
        self._begin_login()
        self.client.post(
            reverse("accounts:mfa-challenge"),
            {"action": "recovery", "recovery_code": self.recovery_codes[0]},
        )
        start_response = self.client.post(
            reverse("accounts:mfa-settings"),
            {"action": "start"},
        )
        enrollment = start_response.context["enrollment"]
        new_totp = pyotp.parse_uri(enrollment.provisioning_uri)
        response = self.client.post(
            reverse("accounts:mfa-confirm"),
            {"code": new_totp.now()},
        )
        self.assertEqual(response.status_code, 200)
        session = self.client.session
        self.assertNotIn(RECOVERY_KEY, session)
        self.assertIn(PRIVILEGED_KEY, session)

    def test_expired_recovery_state_logs_user_out(self):
        self._begin_login()
        self.client.post(
            reverse("accounts:mfa-challenge"),
            {"action": "recovery", "recovery_code": self.recovery_codes[0]},
        )
        session = self.client.session
        session[RECOVERY_KEY]["issued_at"] = (
            timezone.now() - timedelta(minutes=6)
        ).timestamp()
        session.save()
        response = self.client.get(reverse("index"))
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_direct_admin_login_is_centralized(self):
        for login_name in ("admin:login", "cus_admin:login"):
            with self.subTest(login_name=login_name):
                response = self.client.get(reverse(login_name))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_unprivileged_user_login_remains_single_step(self):
        ordinary = MyUser.objects.create_user(
            email="ordinary-h2@example.test",
            username="ordinary_h2",
            password=self.password,
            is_active=True,
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": ordinary.username, "password": self.password},
        )
        self.assertRedirects(response, reverse("index"))
        self.assertEqual(int(self.client.session[SESSION_KEY]), ordinary.pk)
        self.assertNotIn(PENDING_KEY, self.client.session)

    def test_required_user_without_device_is_not_logged_in(self):
        self.device.delete()
        response = self._begin_login()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "尚未绑定动态验证码")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_readiness_preflight_requires_acknowledgement_and_active_material(self):
        with self.assertRaises(CommandError):
            call_command("check_mfa_readiness")
        output = StringIO()
        call_command(
            "check_mfa_readiness",
            acknowledge_recovery_material=True,
            stdout=output,
        )
        self.assertIn("readiness passed", output.getvalue())

        self.device.recovery_codes.all().delete()
        with self.assertRaises(CommandError):
            call_command(
                "check_mfa_readiness",
                acknowledge_recovery_material=True,
            )


@override_settings(
    MFA_TOTP_KEYRING={"test-v1": _encoded_key()},
    MFA_TOTP_ACTIVE_KEY_ID="test-v1",
    MFA_TOTP_ISSUER="PowerAdapter Test",
    MFA_ENFORCEMENT_ENABLED=False,
    LOG_HMAC_KEY=os.urandom(32),
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class H2EnrollmentUiTest(TestCase):
    def test_binding_page_returns_qr_without_persisting_uri(self):
        user = MyUser.objects.create_superuser(
            email="ui-admin@example.test",
            username="ui_admin",
            password="test-only-password",
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("accounts:mfa-settings"),
            {"action": "start"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data:image/png;base64,")
        self.assertContains(response, "MANUAL KEY")
        self.assertIn("no-store", response.headers["Cache-Control"])
        device = MfaTotpDevice.objects.get(user=user)
        self.assertNotIn("otpauth", str(device.__dict__).lower())
