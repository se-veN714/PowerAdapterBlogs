import base64
import os
from datetime import timedelta
from unittest.mock import patch

import pyotp
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.auth.hashers import check_password
from django.test import TestCase, override_settings
from django.utils import timezone

from boards.models import Board, BoardMembership
from security.models import SecureLogEntry

from accounts.authn.mfa_crypto import MfaCryptoError, decode_keyring, decrypt_mfa_secret
from accounts.authn.mfa_services import (
    MfaServiceError,
    _aad,
    _encrypted_value,
    confirm_totp_enrollment,
    consume_recovery_code,
    revoke_totp_device,
    start_totp_enrollment,
)
from accounts.models import MfaRecoveryCode, MfaTotpDevice, MyUser


def _encoded_key():
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


@override_settings(
    MFA_TOTP_KEYRING={"test-v1": _encoded_key()},
    MFA_TOTP_ACTIVE_KEY_ID="test-v1",
    MFA_TOTP_ISSUER="PowerAdapter Test",
    MFA_TOTP_BINDING_TTL_SECONDS=600,
    MFA_TOTP_VALID_WINDOW=1,
    MFA_RECOVERY_CODE_COUNT=10,
    LOG_HMAC_KEY=os.urandom(32),
)
class MfaEnrollmentServiceTest(TestCase):
    def setUp(self):
        self.user = MyUser.objects.create_superuser(
            email="mfa-admin@example.test",
            username="mfa_admin",
            password="test-only-password",
        )

    def _start(self):
        return start_totp_enrollment(user=self.user, actor=self.user)

    def _valid_code(self, enrollment):
        return pyotp.parse_uri(enrollment.provisioning_uri).now()

    def _invalid_code(self, enrollment):
        totp = pyotp.parse_uri(enrollment.provisioning_uri)
        now = timezone.now()
        current_step = totp.timecode(now)
        accepted = {
            totp.generate_otp(current_step + offset)
            for offset in range(
                -settings.MFA_TOTP_VALID_WINDOW, settings.MFA_TOTP_VALID_WINDOW + 1
            )
        }
        return next(
            f"{candidate:06d}"
            for candidate in range(1_000_000)
            if f"{candidate:06d}" not in accepted
        )

    def _activate(self):
        enrollment = self._start()
        confirmation = confirm_totp_enrollment(
            user=self.user,
            actor=self.user,
            code=self._valid_code(enrollment),
        )
        return enrollment, confirmation

    def test_missing_keyring_fails_before_device_is_created(self):
        with override_settings(MFA_TOTP_KEYRING={}, MFA_TOTP_ACTIVE_KEY_ID=""):
            with self.assertRaises(MfaServiceError) as context:
                self._start()
        self.assertEqual(context.exception.reason, "keyring_unavailable")
        self.assertFalse(MfaTotpDevice.objects.exists())

    def test_invalid_security_settings_fail_before_device_is_created(self):
        invalid_settings = (
            {"MFA_TOTP_KEYRING": {1: _encoded_key()}},
            {"MFA_TOTP_BINDING_TTL_SECONDS": 0},
            {"MFA_TOTP_ISSUER": ""},
        )
        for overrides in invalid_settings:
            with self.subTest(overrides=overrides), override_settings(**overrides):
                with self.assertRaises(MfaServiceError):
                    self._start()
                self.assertFalse(MfaTotpDevice.objects.exists())

    def test_pending_seed_is_encrypted_and_uri_is_not_persisted(self):
        enrollment = self._start()
        device = MfaTotpDevice.objects.get(user=self.user)
        seed = pyotp.parse_uri(enrollment.provisioning_uri).secret.encode("ascii")

        self.assertEqual(device.status, MfaTotpDevice.Status.PENDING)
        self.assertNotIn(seed, bytes(device.secret_ciphertext))
        self.assertNotIn("otpauth", str(device.__dict__).lower())
        self.assertGreater(device.binding_expires_at, timezone.now())
        self.assertLessEqual(
            device.binding_expires_at,
            timezone.now() + timedelta(minutes=10, seconds=2),
        )

    def test_manager_can_enroll_but_ordinary_user_cannot(self):
        manager = MyUser.objects.create_user(
            email="manager@example.test",
            username="board_manager",
            password="test-only-password",
            is_active=True,
        )
        board = Board.objects.create(slug="mfa-board", name="MFA Board")
        BoardMembership.objects.create(
            board=board,
            user=manager,
            role=BoardMembership.Role.MANAGER,
            created_by=self.user,
        )
        enrollment = start_totp_enrollment(user=manager, actor=manager)
        self.assertEqual(enrollment.device_id, manager.mfa_totp_device.pk)

        ordinary = MyUser.objects.create_user(
            email="ordinary@example.test",
            username="ordinary",
            password="test-only-password",
            is_active=True,
        )
        with self.assertRaises(MfaServiceError) as context:
            start_totp_enrollment(user=ordinary, actor=ordinary)
        self.assertEqual(context.exception.reason, "not_allowed")

    def test_dashboard_user_can_enroll(self):
        dashboard_user = MyUser.objects.create_user(
            email="dashboard-mfa@example.test",
            username="dashboard_mfa",
            password="test-only-password",
            is_active=True,
            is_dashboard_user=True,
        )

        enrollment = start_totp_enrollment(
            user=dashboard_user,
            actor=dashboard_user,
        )

        self.assertEqual(enrollment.device_id, dashboard_user.mfa_totp_device.pk)

    def test_invalid_code_does_not_activate_and_is_hmac_audited(self):
        enrollment = self._start()
        invalid_code = self._invalid_code(enrollment)
        with self.assertRaises(MfaServiceError) as context:
            confirm_totp_enrollment(
                user=self.user,
                actor=self.user,
                code=invalid_code,
            )
        self.assertEqual(context.exception.reason, "invalid_code")
        self.assertEqual(
            self.user.mfa_totp_device.status,
            MfaTotpDevice.Status.PENDING,
        )
        entry = LogEntry.objects.filter(
            change_message__contains="enrollment_failed"
        ).get()
        self.assertNotIn(invalid_code, entry.change_message)
        self.assertTrue(SecureLogEntry.objects.filter(log_entry=entry).exists())

    def test_confirmation_is_once_only_and_recovery_codes_are_hash_only(self):
        _enrollment, confirmation = self._activate()
        device = MfaTotpDevice.objects.get(user=self.user)
        stored_codes = list(device.recovery_codes.all())

        self.assertEqual(device.status, MfaTotpDevice.Status.ACTIVE)
        self.assertIsNotNone(device.confirmed_at)
        self.assertIsNotNone(device.last_accepted_step)
        self.assertEqual(len(confirmation.recovery_codes), 10)
        self.assertEqual(len(stored_codes), 10)
        for plaintext in confirmation.recovery_codes:
            self.assertFalse(
                MfaRecoveryCode.objects.filter(code_digest=plaintext).exists()
            )
        self.assertTrue(
            any(
                check_password(confirmation.recovery_codes[0], item.code_digest)
                for item in stored_codes
            )
        )
        with self.assertRaises(MfaServiceError) as context:
            confirm_totp_enrollment(
                user=self.user,
                actor=self.user,
                code="000000",
            )
        self.assertEqual(context.exception.reason, "not_pending")

    def test_expired_binding_is_cryptographically_erased_and_audited(self):
        self._start()
        device = MfaTotpDevice.objects.get(user=self.user)
        MfaTotpDevice.objects.filter(pk=device.pk).update(
            binding_expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(MfaServiceError) as context:
            confirm_totp_enrollment(user=self.user, actor=self.user, code="000000")
        self.assertEqual(context.exception.reason, "binding_expired")

        device.refresh_from_db()
        self.assertEqual(device.status, MfaTotpDevice.Status.REVOKED)
        self.assertIsNotNone(device.revoked_at)
        with self.assertRaises(MfaCryptoError):
            decrypt_mfa_secret(
                _encrypted_value(device),
                keyring=decode_keyring(settings.MFA_TOTP_KEYRING),
                associated_data=_aad(device),
            )
        entry = LogEntry.objects.filter(
            change_message__contains="enrollment_expired"
        ).get()
        self.assertTrue(SecureLogEntry.objects.filter(log_entry=entry).exists())

    def test_recovery_code_is_consumed_once_without_creating_login_state(self):
        _enrollment, confirmation = self._activate()
        recovery_code = confirmation.recovery_codes[0]
        self.assertTrue(
            consume_recovery_code(
                user=self.user,
                actor=self.user,
                code=recovery_code,
            )
        )
        self.assertFalse(
            consume_recovery_code(
                user=self.user,
                actor=self.user,
                code=recovery_code,
            )
        )
        self.assertEqual(
            MfaRecoveryCode.objects.filter(used_at__isnull=False).count(),
            1,
        )

    def test_recovery_code_lost_race_fails_closed(self):
        _enrollment, confirmation = self._activate()
        recovery_code = confirmation.recovery_codes[0]
        with patch("django.db.models.query.QuerySet.update", return_value=0):
            self.assertFalse(
                consume_recovery_code(
                    user=self.user,
                    actor=self.user,
                    code=recovery_code,
                )
            )
        self.assertFalse(MfaRecoveryCode.objects.filter(used_at__isnull=False).exists())

    def test_self_revoke_requires_password_and_erases_recovery_material(self):
        self._activate()
        device = MfaTotpDevice.objects.get(user=self.user)
        original_ciphertext = bytes(device.secret_ciphertext)
        original_version = device.auth_version
        with self.assertRaises(MfaServiceError) as context:
            revoke_totp_device(
                target_user=self.user,
                actor=self.user,
                current_password="wrong-password",
            )
        self.assertEqual(context.exception.reason, "reset_not_allowed")

        with self.assertRaises(MfaServiceError) as context:
            revoke_totp_device(
                target_user=self.user,
                actor=self.user,
                current_password="test-only-password",
            )
        self.assertEqual(context.exception.reason, "invalid_code")

        with patch(
            "accounts.authn.mfa_services._matching_step",
            return_value=device.last_accepted_step + 1,
        ):
            revoked = revoke_totp_device(
                target_user=self.user,
                actor=self.user,
                current_password="test-only-password",
                totp_code="123456",
                reason="test-only-password",
            )
        self.assertEqual(revoked.status, MfaTotpDevice.Status.REVOKED)
        self.assertEqual(revoked.auth_version, original_version + 1)
        self.assertNotEqual(bytes(revoked.secret_ciphertext), original_ciphertext)
        self.assertFalse(revoked.recovery_codes.exists())
        entry = LogEntry.objects.filter(change_message__contains="device_revoked").get()
        self.assertNotIn("test-only-password", entry.change_message)
        self.assertIn("reason=operator_reset", entry.change_message)
        self.assertTrue(SecureLogEntry.objects.filter(log_entry=entry).exists())

    def test_another_active_superuser_can_reset_without_target_password(self):
        self._activate()
        operator = MyUser.objects.create_superuser(
            email="operator@example.test",
            username="mfa_operator",
            password="operator-password",
        )
        revoked = revoke_totp_device(target_user=self.user, actor=operator)
        self.assertEqual(revoked.status, MfaTotpDevice.Status.REVOKED)

    def test_audit_payload_never_contains_seed_totp_or_recovery_codes(self):
        enrollment, confirmation = self._activate()
        sensitive_values = (
            pyotp.parse_uri(enrollment.provisioning_uri).secret,
            self._valid_code(enrollment),
            *confirmation.recovery_codes,
        )
        audit_payload = "\n".join(
            LogEntry.objects.values_list("change_message", flat=True)
        )
        for value in sensitive_values:
            self.assertNotIn(value, audit_payload)
