import base64
import os
from datetime import timedelta
from unittest.mock import patch

import pyotp
from django.contrib.auth import SESSION_KEY
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from security.models import SecureLogEntry

from accounts.authn.mfa_services import confirm_totp_enrollment, start_totp_enrollment
from accounts.authn.mfa_session import PENDING_KEY, PRIVILEGED_KEY
from accounts.authn.mtls_services import (
    MtlsServiceError,
    bind_client_certificate,
    resolve_client_certificate,
    revoke_client_certificate,
)
from accounts.models import ClientCertificateBinding, MfaTotpDevice, MyUser


def _encoded_key():
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


H3_SETTINGS = {
    "ALLOWED_HOSTS": ["admin.example.test", "testserver"],
    "MTLS_ENFORCEMENT_ENABLED": True,
    "MTLS_ADMIN_HOST": "admin.example.test",
    "MTLS_TRUSTED_PROXY_NETWORKS": ("127.0.0.1/32",),
    "MTLS_PROXY_AUTH_SECRET": "test-only-proxy-secret-at-least-32-bytes",
    "MTLS_CERTIFICATE_PROFILE": "standard-tls",
    "MFA_TOTP_KEYRING": {"test-v1": _encoded_key()},
    "MFA_TOTP_ACTIVE_KEY_ID": "test-v1",
    "MFA_TOTP_ISSUER": "PowerAdapter Test",
    "MFA_TOTP_BINDING_TTL_SECONDS": 600,
    "MFA_TOTP_VALID_WINDOW": 1,
    "MFA_RECOVERY_CODE_COUNT": 10,
    "MFA_ENFORCEMENT_ENABLED": True,
    "MFA_CHALLENGE_TTL_SECONDS": 300,
    "MFA_CHALLENGE_MAX_ATTEMPTS": 5,
    "MFA_CHALLENGE_COOLDOWN_SECONDS": 900,
    "MFA_PRIVILEGED_SESSION_TTL_SECONDS": 900,
    "LOG_HMAC_KEY": os.urandom(32),
    "PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"],
}


@override_settings(**H3_SETTINGS)
class ClientCertificateServiceTest(TestCase):
    def setUp(self):
        self.user = MyUser.objects.create_superuser(
            email="cert-admin@example.test",
            username="cert_admin",
            password="test-password",
        )
        self.binding = bind_client_certificate(
            user=self.user,
            actor=self.user,
            serial_number="01:AB:CD",
            issuer_dn="CN=PowerAdapter Client CA,O=PowerAdapter",
            subject_dn="CN=cert_admin,O=PowerAdapter",
            certificate_profile="standard-tls",
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.factory = RequestFactory()

    def _request(self, **overrides):
        values = {
            "HTTP_HOST": "admin.example.test",
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_X_PA_PROXY_AUTH": H3_SETTINGS["MTLS_PROXY_AUTH_SECRET"],
            "HTTP_X_PA_MTLS_VERIFY": "SUCCESS",
            "HTTP_X_PA_MTLS_SERIAL": "01ABCD",
            "HTTP_X_PA_MTLS_ISSUER_DN": self.binding.issuer_dn,
            "HTTP_X_PA_MTLS_SUBJECT_DN": self.binding.subject_dn,
            "HTTP_X_PA_MTLS_PROFILE": "standard-tls",
        }
        values.update(overrides)
        return self.factory.get("/super_admin/", **values)

    def test_trusted_proxy_metadata_resolves_active_binding(self):
        resolved = resolve_client_certificate(
            self._request(),
            expected_user=self.user,
        )
        self.assertEqual(resolved.pk, self.binding.pk)

    def test_forged_headers_from_untrusted_transport_are_rejected(self):
        for overrides in (
            {"REMOTE_ADDR": "198.51.100.20"},
            {"HTTP_X_PA_PROXY_AUTH": "attacker-controlled"},
            {"HTTP_HOST": "poweradapter.example.test"},
            {"HTTP_X_PA_MTLS_VERIFY": "FAILED:certificate expired"},
            {"HTTP_X_PA_MTLS_PROFILE": "sm2-tlcp"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(MtlsServiceError):
                    resolve_client_certificate(self._request(**overrides))

    @override_settings(
        MTLS_TRUSTED_PROXY_NETWORKS=(),
        MTLS_TRUST_UNIX_SOCKET_PROXY=True,
    )
    def test_private_unix_socket_mode_accepts_empty_remote_address(self):
        resolved = resolve_client_certificate(self._request(REMOTE_ADDR=""))
        self.assertEqual(resolved.pk, self.binding.pk)

    def test_subject_user_expiry_and_revocation_are_fail_closed(self):
        with self.assertRaises(MtlsServiceError):
            resolve_client_certificate(
                self._request(HTTP_X_PA_MTLS_SUBJECT_DN="CN=attacker"),
            )

        other = MyUser.objects.create_superuser(
            email="other-cert-admin@example.test",
            username="other_cert_admin",
            password="test-password",
        )
        with self.assertRaises(MtlsServiceError):
            resolve_client_certificate(self._request(), expected_user=other)

        ClientCertificateBinding.objects.filter(pk=self.binding.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(MtlsServiceError):
            resolve_client_certificate(self._request())
        ClientCertificateBinding.objects.filter(pk=self.binding.pk).update(
            expires_at=timezone.now() + timedelta(days=30)
        )
        revoke_client_certificate(
            binding=self.binding,
            actor=self.user,
            reason="rotated",
        )
        with self.assertRaises(MtlsServiceError):
            resolve_client_certificate(self._request())
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.auth_version, 2)
        self.assertTrue(
            SecureLogEntry.objects.filter(
                log_entry__object_id=str(self.binding.pk),
            ).exists()
        )

    def test_binding_rejects_non_superuser_and_duplicate_certificate(self):
        ordinary = MyUser.objects.create_user(
            email="ordinary@example.test",
            username="ordinary",
            password="test-password",
            is_active=True,
        )
        with self.assertRaises(MtlsServiceError):
            bind_client_certificate(
                user=ordinary,
                actor=self.user,
                serial_number="99",
                issuer_dn=self.binding.issuer_dn,
                subject_dn="CN=ordinary",
                certificate_profile="standard-tls",
                expires_at=timezone.now() + timedelta(days=1),
            )
        with self.assertRaises(MtlsServiceError):
            bind_client_certificate(
                user=self.user,
                actor=self.user,
                serial_number=self.binding.serial_number,
                issuer_dn=self.binding.issuer_dn,
                subject_dn=self.binding.subject_dn,
                certificate_profile="standard-tls",
                expires_at=timezone.now() + timedelta(days=1),
            )

    def test_readiness_requires_all_operational_acknowledgements(self):
        with self.assertRaises(CommandError):
            call_command("check_mtls_readiness")
        acknowledgements = {
            "acknowledge_proxy_boundary": True,
            "acknowledge_client_ca": True,
            "acknowledge_revocation": True,
            "acknowledge_break_glass": True,
            "acknowledge_openssl_4": True,
        }
        for missing in acknowledgements:
            options = acknowledgements | {missing: False}
            with self.subTest(missing=missing), self.assertRaises(CommandError):
                call_command("check_mtls_readiness", **options)
        call_command(
            "check_mtls_readiness",
            **acknowledgements,
        )

    @override_settings(MTLS_CERTIFICATE_PROFILE="sm2-tlcp")
    def test_tlcp_profile_cannot_enter_production_readiness_or_resolution(self):
        with self.assertRaises(MtlsServiceError):
            resolve_client_certificate(
                self._request(HTTP_X_PA_MTLS_PROFILE="sm2-tlcp")
            )
        with self.assertRaises(CommandError):
            call_command(
                "check_mtls_readiness",
                acknowledge_proxy_boundary=True,
                acknowledge_client_ca=True,
                acknowledge_revocation=True,
                acknowledge_break_glass=True,
                acknowledge_openssl_4=True,
            )


@override_settings(**H3_SETTINGS)
class H3AdminAuthenticationTest(TestCase):
    password = "test-password"

    def setUp(self):
        self.user = MyUser.objects.create_superuser(
            email="h3-admin@example.test",
            username="h3_admin",
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
            serial_number="A100",
            issuer_dn="CN=PowerAdapter Client CA,O=PowerAdapter",
            subject_dn="CN=h3_admin,O=PowerAdapter",
            certificate_profile="standard-tls",
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.headers = {
            "HTTP_HOST": "admin.example.test",
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_X_PA_PROXY_AUTH": H3_SETTINGS["MTLS_PROXY_AUTH_SECRET"],
            "HTTP_X_PA_MTLS_VERIFY": "SUCCESS",
            "HTTP_X_PA_MTLS_SERIAL": self.binding.serial_number,
            "HTTP_X_PA_MTLS_ISSUER_DN": self.binding.issuer_dn,
            "HTTP_X_PA_MTLS_SUBJECT_DN": self.binding.subject_dn,
            "HTTP_X_PA_MTLS_PROFILE": "standard-tls",
        }

    def _login(self, headers=None):
        return self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.username,
                "password": self.password,
                "next": reverse("admin:index"),
            },
            **(headers or {}),
        )

    def _fresh_step_and_code(self):
        self.device.refresh_from_db()
        step = (
            self.device.last_accepted_step or self.totp.timecode(timezone.now())
        ) + 1
        return step, self.totp.generate_otp(step)

    def test_system_admin_login_requires_certificate_before_totp(self):
        response = self._login()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assertNotIn(SESSION_KEY, self.client.session)

        response = self._login(self.headers)
        self.assertRedirects(
            response,
            reverse("accounts:mfa-challenge"),
            fetch_redirect_response=False,
        )
        pending = self.client.session[PENDING_KEY]
        self.assertEqual(pending["certificate_binding_id"], str(self.binding.pk))

    def test_challenge_rechecks_certificate_and_binds_privileged_session(self):
        self._login(self.headers)
        step, code = self._fresh_step_and_code()
        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
            missing = self.client.post(
                reverse("accounts:mfa-challenge"),
                {"action": "totp", "code": code},
                HTTP_HOST="admin.example.test",
            )
        self.assertEqual(missing.status_code, 403)
        self.assertNotIn(SESSION_KEY, self.client.session)

        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
            response = self.client.post(
                reverse("accounts:mfa-challenge"),
                {"action": "totp", "code": code},
                **self.headers,
            )
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertIn(SESSION_KEY, session)
        self.assertEqual(
            session[PRIVILEGED_KEY]["certificate_binding_id"],
            str(self.binding.pk),
        )
        admin = self.client.get(reverse("admin:index"), **self.headers)
        self.assertEqual(admin.status_code, 200)

    def test_direct_admin_header_spoof_and_revocation_are_rejected(self):
        spoofed = dict(self.headers)
        spoofed["REMOTE_ADDR"] = "198.51.100.20"
        self.assertEqual(
            self.client.get(reverse("admin:index"), **spoofed).status_code,
            403,
        )

        self._login(self.headers)
        step, code = self._fresh_step_and_code()
        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
            self.client.post(
                reverse("accounts:mfa-challenge"),
                {"action": "totp", "code": code},
                **self.headers,
            )
        revoke_client_certificate(
            binding=self.binding,
            actor=self.user,
            reason="suspected_compromise",
        )
        self.assertEqual(
            self.client.get(reverse("admin:index"), **self.headers).status_code,
            403,
        )

    def test_super_admin_session_is_bound_to_the_presented_certificate(self):
        self._login(self.headers)
        step, code = self._fresh_step_and_code()
        with patch("accounts.authn.mfa_services._matching_step", return_value=step):
            self.client.post(
                reverse("accounts:mfa-challenge"),
                {"action": "totp", "code": code},
                **self.headers,
            )
        replacement = bind_client_certificate(
            user=self.user,
            actor=self.user,
            serial_number="A101",
            issuer_dn=self.binding.issuer_dn,
            subject_dn=self.binding.subject_dn,
            certificate_profile="standard-tls",
            expires_at=timezone.now() + timedelta(days=30),
        )
        replacement_headers = {
            **self.headers,
            "HTTP_X_PA_MTLS_SERIAL": replacement.serial_number,
        }
        response = self.client.get(reverse("admin:index"), **replacement_headers)
        self.assertRedirects(
            response,
            reverse("accounts:mfa-challenge"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.session[PENDING_KEY]["certificate_binding_id"],
            str(replacement.pk),
        )

    @override_settings(MFA_ENFORCEMENT_ENABLED=False)
    def test_mtls_cannot_run_with_password_only_admin(self):
        response = self.client.get(reverse("admin:index"), **self.headers)
        self.assertEqual(response.status_code, 500)
