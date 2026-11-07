import base64
import os
from io import StringIO
from datetime import timedelta
from unittest.mock import patch

import pyotp
from django.contrib.auth import SESSION_KEY
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from security.models import AuditOutbox

from accounts.authn.mfa_services import (
    MfaServiceError,
    confirm_totp_enrollment,
    start_totp_enrollment,
    verify_active_totp,
)
from accounts.authn.mfa_session import (
    DASHBOARD_REMEMBER_KEY,
    ENROLLMENT_KEY,
    PENDING_KEY,
    PRIVILEGED_KEY,
    RECOVERY_KEY,
)
from accounts.models import MfaTotpDevice, MyUser
from accounts.services import (
    EMAIL_PURPOSE_MFA_ENROLLMENT,
    MFA_ENROLLMENT_EMAIL_VERIFIED_SESSION_KEY,
)


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
    MFA_DASHBOARD_REMEMBER_TTL_SECONDS=7 * 24 * 60 * 60,
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
        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
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
        self.assertEqual(session[PENDING_KEY]["target"], reverse("dashboard:overview"))
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

    def test_dashboard_can_be_remembered_for_seven_days_without_relaxing_super_admin(self):
        dashboard_url = reverse("dashboard:overview")
        self._begin_login(target=dashboard_url)
        challenge_page = self.client.get(reverse("accounts:mfa-challenge"))
        self.assertContains(challenge_page, "信任当前浏览器 7 天")

        step, code = self._fresh_step_and_code()
        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
            response = self.client.post(
                reverse("accounts:mfa-challenge"),
                {
                    "action": "totp",
                    "code": code,
                    "remember_dashboard": "on",
                },
            )
        self.assertRedirects(response, dashboard_url, fetch_redirect_response=False)
        session = self.client.session
        self.assertIn(DASHBOARD_REMEMBER_KEY, session)
        session[PRIVILEGED_KEY]["verified_at"] = (
            timezone.now() - timedelta(minutes=16)
        ).timestamp()
        session.save()

        self.assertEqual(self.client.get(dashboard_url).status_code, 200)
        self.assertRedirects(
            self.client.get(reverse("admin:index")),
            reverse("accounts:mfa-challenge"),
            fetch_redirect_response=False,
        )
        MfaTotpDevice.objects.filter(pk=self.device.pk).update(auth_version=2)
        self.assertRedirects(
            self.client.get(dashboard_url),
            reverse("accounts:mfa-challenge"),
            fetch_redirect_response=False,
        )

    def _trust_dashboard_browser(self):
        self._begin_login(target=reverse("dashboard:overview"))
        step, code = self._fresh_step_and_code()
        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
            return self.client.post(reverse("accounts:mfa-challenge"), {
                "action": "totp", "code": code, "remember_dashboard": "on",
            })

    def test_dashboard_trust_survives_login_session_expiry_without_granting_admin_freshness(self):
        from django.conf import settings
        self._trust_dashboard_browser()
        # A closed browser/expired login loses the login cookie, not persistent browser cookies.
        self.client.cookies.pop(settings.SESSION_COOKIE_NAME, None)
        response = self._begin_login(target=reverse("dashboard:overview"))
        self.assertRedirects(response, reverse("dashboard:overview"), fetch_redirect_response=False)
        self.assertNotIn(PRIVILEGED_KEY, self.client.session)
        self.assertEqual(self.client.get(reverse("dashboard:overview")).status_code, 200)
        self.assertRedirects(self.client.get(reverse("admin:index")), reverse("accounts:mfa-challenge"), fetch_redirect_response=False)

    def test_trust_cookie_is_persistent_host_only_and_http_only(self):
        from accounts.authn.mfa_session import DASHBOARD_TRUST_COOKIE
        self._begin_login(target=reverse("dashboard:overview"))
        step, code = self._fresh_step_and_code()
        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
            response = self.client.post(reverse("accounts:mfa-challenge"), {"code": code, "remember_dashboard": "on"}, secure=True)
        cookie = response.cookies[DASHBOARD_TRUST_COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["domain"], "")
        self.assertTrue(0 < int(cookie["max-age"]) <= 604800)

    def test_trust_survives_explicit_logout_but_password_is_still_required(self):
        self._trust_dashboard_browser()
        self.client.post(reverse("accounts:logout"))
        response = self.client.post(reverse("accounts:login"), {"username": self.user.username, "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertRedirects(self._begin_login(target=reverse("dashboard:overview")), reverse("dashboard:overview"), fetch_redirect_response=False)
        self.assertNotIn(PRIVILEGED_KEY, self.client.session)

    def test_trust_never_renews_on_login_and_expires_at_seven_days(self):
        from django.conf import settings
        from accounts.authn.mfa_session import DASHBOARD_TRUST_COOKIE
        self._trust_dashboard_browser()
        original = self.client.session[DASHBOARD_REMEMBER_KEY].copy()
        for days, target in [(6, reverse("dashboard:overview")), (7, reverse("accounts:mfa-challenge"))]:
            self.client.cookies.pop(settings.SESSION_COOKIE_NAME, None)
            when = timezone.datetime.fromtimestamp(original["expires_at"], timezone.get_current_timezone()) - timedelta(days=7-days)
            with patch("accounts.authn.mfa_session.timezone.now", return_value=when):
                response = self._begin_login(target=reverse("dashboard:overview"))
            self.assertRedirects(response, target, fetch_redirect_response=False)
            self.assertNotIn(DASHBOARD_TRUST_COOKIE, response.cookies)
            if days == 6:
                self.assertEqual(self.client.session[DASHBOARD_REMEMBER_KEY]["expires_at"], original["expires_at"])

    def test_bad_signature_password_reset_and_device_revocation_invalidate_browser_trust(self):
        from django.conf import settings
        from accounts.authn.mfa_session import DASHBOARD_TRUST_COOKIE
        self._trust_dashboard_browser()
        cookie = self.client.cookies[DASHBOARD_TRUST_COOKIE].value
        original_password = self.user.password
        cases = ["tampered", "password", "device"]
        for case in cases:
            with self.subTest(case=case):
                self.user.password = original_password
                self.user.save(update_fields=["password"])
                MfaTotpDevice.objects.filter(pk=self.device.pk).update(auth_version=self.device.auth_version)
                self.client.cookies.pop(settings.SESSION_COOKIE_NAME, None)
                self.client.cookies[DASHBOARD_TRUST_COOKIE] = cookie + 'broken' if case == 'tampered' else cookie
                if case == 'password':
                    self.user.set_password(self.password)
                    self.user.save(update_fields=['password'])
                if case == 'device':
                    MfaTotpDevice.objects.filter(pk=self.device.pk).update(auth_version=self.device.auth_version + 1)
                response = self._begin_login(target=reverse("dashboard:overview"))
                self.assertRedirects(response, reverse("accounts:mfa-challenge"), fetch_redirect_response=False)
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_browser_trust_cannot_authenticate_or_apply_to_another_account(self):
        from django.conf import settings
        from django.test import RequestFactory
        from accounts.authn.mfa_session import dashboard_browser_grant, DASHBOARD_TRUST_COOKIE
        self._trust_dashboard_browser()
        cookie = self.client.cookies[DASHBOARD_TRUST_COOKIE].value
        other = MyUser.objects.create_superuser(email='other-trust@example.test', username='other-trust', password=self.password)
        request = RequestFactory().get('/')
        request.COOKIES[DASHBOARD_TRUST_COOKIE] = cookie
        self.assertIsNone(dashboard_browser_grant(request, other))
        self.client.cookies.pop(settings.SESSION_COOKIE_NAME, None)
        response = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertRedirects(self._begin_login(target=reverse("admin:index")), reverse("accounts:mfa-challenge"), fetch_redirect_response=False)

    def test_unchecked_trust_cannot_issue_a_persistent_grant(self):
        from accounts.authn.mfa_session import DASHBOARD_TRUST_COOKIE
        self._begin_login(target=reverse("dashboard:overview"))
        step, code = self._fresh_step_and_code()
        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
            response = self.client.post(reverse("accounts:mfa-challenge"), {"code": code})
        self.assertNotIn(DASHBOARD_REMEMBER_KEY, self.client.session)
        self.assertEqual(response.cookies[DASHBOARD_TRUST_COOKIE]['max-age'], 0)

    def test_trust_countdown_is_present_and_does_not_extend_the_grant(self):
        self._trust_dashboard_browser()
        expires_at = self.client.session[DASHBOARD_REMEMBER_KEY]["expires_at"]
        for url in [reverse("dashboard:overview"), reverse("accounts:mfa-settings")]:
            response = self.client.get(url)
            self.assertContains(response, 'data-mfa-trust-countdown')
            self.assertContains(response, '仅用于 /dashboard/')
            self.assertGreater(response.context['dashboard_browser_trust']['remaining_seconds'], 0)
        self.assertEqual(self.client.session[DASHBOARD_REMEMBER_KEY]["expires_at"], expires_at)

    def test_super_admin_challenge_never_offers_dashboard_remember_option(self):
        self._begin_login(target=reverse("admin:index"))
        response = self.client.get(reverse("accounts:mfa-challenge"))
        self.assertNotContains(response, "信任当前浏览器 7 天")

    def test_same_totp_step_cannot_be_replayed(self):
        step, code = self._fresh_step_and_code()
        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
            verify_active_totp(user=self.user, actor=self.user, code=code)
            with self.assertRaises(MfaServiceError) as context:
                verify_active_totp(user=self.user, actor=self.user, code=code)
        self.assertEqual(context.exception.reason, "replayed_code")
        self.assertTrue(
            AuditOutbox.objects.filter(
                event_type="mfa.challenge_failed",
                event__outcome__error_code="REPLAYED_CODE",
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
        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
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
        self.assertRedirects(
            response,
            reverse("accounts:mfa-settings"),
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            self.client.get(reverse("accounts:mfa-settings")),
            reverse("accounts:mfa-enrollment-email-verify"),
        )
        session = self.client.session
        self.assertIn(SESSION_KEY, session)
        self.assertIn(RECOVERY_KEY, session)
        self.assertNotIn(PRIVILEGED_KEY, session)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, MfaTotpDevice.Status.REVOKED)
        self.assertRedirects(
            self.client.get(reverse("index")),
            reverse("accounts:mfa-settings"),
            fetch_redirect_response=False,
        )

    def test_recovery_rebind_clears_restriction_and_issues_privilege(self):
        self._begin_login()
        self.client.post(
            reverse("accounts:mfa-challenge"),
            {"action": "recovery", "recovery_code": self.recovery_codes[0]},
        )
        session = self.client.session
        session[MFA_ENROLLMENT_EMAIL_VERIFIED_SESSION_KEY] = {
            "user_id": self.user.pk,
            "purpose": EMAIL_PURPOSE_MFA_ENROLLMENT,
            "verified_at": timezone.now().timestamp(),
        }
        session.save()
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

    def test_required_user_without_device_enters_restricted_enrollment(self):
        self.device.delete()
        response = self._begin_login()
        self.assertRedirects(
            response,
            reverse("accounts:mfa-enrollment-email-verify"),
            fetch_redirect_response=False,
        )
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.user.pk)
        self.assertIn(ENROLLMENT_KEY, self.client.session)
        self.assertRedirects(
            self.client.get(reverse("index")),
            reverse("accounts:mfa-enrollment-email-verify"),
            fetch_redirect_response=False,
        )

    def test_initial_enrollment_clears_restriction_after_totp_confirmation(self):
        self.device.delete()
        self._begin_login()
        session = self.client.session
        session[MFA_ENROLLMENT_EMAIL_VERIFIED_SESSION_KEY] = {
            "user_id": self.user.pk,
            "purpose": EMAIL_PURPOSE_MFA_ENROLLMENT,
            "verified_at": timezone.now().timestamp(),
        }
        session.save()

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
        self.assertNotIn(ENROLLMENT_KEY, session)
        self.assertIn(PRIVILEGED_KEY, session)

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
    MFA_ENROLLMENT_MODE_ENABLED=True,
    SECURE_SSL_REDIRECT=False,
    LOG_HMAC_KEY=os.urandom(32),
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class H2EnrollmentUiTest(TestCase):
    def _mark_email_verified(self, user):
        session = self.client.session
        session[MFA_ENROLLMENT_EMAIL_VERIFIED_SESSION_KEY] = {
            "user_id": user.pk,
            "purpose": EMAIL_PURPOSE_MFA_ENROLLMENT,
            "verified_at": timezone.now().timestamp(),
        }
        session.save()

    def test_initial_binding_redirects_to_email_verification(self):
        user = MyUser.objects.create_superuser(
            email="email-gate-admin@example.test",
            username="email_gate_admin",
            password="test-only-password",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:mfa-settings"))

        self.assertRedirects(
            response,
            reverse("accounts:mfa-enrollment-email-verify"),
        )

    def test_enrollment_mode_confines_privileged_session_to_mfa_routes(self):
        user = MyUser.objects.create_superuser(
            email="confined-admin@example.test",
            username="confined_admin",
            password="test-only-password",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:overview"))

        self.assertRedirects(
            response,
            reverse("accounts:mfa-settings"),
            fetch_redirect_response=False,
        )

    def test_binding_page_returns_qr_without_persisting_uri(self):
        user = MyUser.objects.create_superuser(
            email="ui-admin@example.test",
            username="ui_admin",
            password="test-only-password",
        )
        self.client.force_login(user)
        self._mark_email_verified(user)
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
