import os
import uuid
from datetime import timedelta

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .mfa_crypto import (
    EncryptedMfaSecret,
    MfaCryptoError,
    build_mfa_device_aad,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
)
from .models import MfaRecoveryCode, MfaTotpDevice, MyUser


class MfaTotpDeviceModelTest(TestCase):
    def setUp(self):
        self.user = MyUser.objects.create_user(
            email="mfa-model@example.test",
            username="mfa_model_user",
            password="test-only-password",
        )
        self.keyring = {"test-v1": os.urandom(32)}

    def _device_kwargs(self, **overrides):
        device_id = overrides.pop("id", uuid.uuid4())
        seed = overrides.pop("seed", os.urandom(20))
        aad = build_mfa_device_aad(user_id=self.user.pk, device_id=device_id)
        encrypted = encrypt_mfa_secret(
            seed,
            keyring=self.keyring,
            active_key_id="test-v1",
            associated_data=aad,
        )
        values = {
            "id": device_id,
            "user": self.user,
            "secret_ciphertext": encrypted.ciphertext,
            "secret_nonce": encrypted.nonce,
            "key_id": encrypted.key_id,
            "binding_expires_at": timezone.now() + timedelta(minutes=10),
        }
        values.update(overrides)
        return values, seed

    def test_seed_is_encrypted_before_database_write_and_bound_to_device(self):
        values, seed = self._device_kwargs()
        device = MfaTotpDevice.objects.create(**values)
        stored = MfaTotpDevice.objects.get(pk=device.pk)

        self.assertNotIn(seed, bytes(stored.secret_ciphertext))
        encrypted = EncryptedMfaSecret(
            stored.key_id,
            bytes(stored.secret_nonce),
            bytes(stored.secret_ciphertext),
        )
        aad = build_mfa_device_aad(user_id=self.user.pk, device_id=stored.pk)
        self.assertEqual(
            decrypt_mfa_secret(encrypted, keyring=self.keyring, associated_data=aad),
            seed,
        )
        with self.assertRaises(MfaCryptoError):
            decrypt_mfa_secret(
                encrypted,
                keyring=self.keyring,
                associated_data=build_mfa_device_aad(
                    user_id=self.user.pk,
                    device_id=uuid.uuid4(),
                ),
            )

    def test_model_has_no_plaintext_seed_or_provisioning_uri_field(self):
        field_names = {field.name for field in MfaTotpDevice._meta.get_fields()}
        self.assertTrue({"secret_ciphertext", "secret_nonce", "key_id"} <= field_names)
        self.assertTrue(
            {"secret", "seed", "plaintext_seed", "otpauth_uri"}.isdisjoint(field_names)
        )

    def test_one_user_cannot_have_two_totp_devices(self):
        values, _ = self._device_kwargs()
        MfaTotpDevice.objects.create(**values)
        second_values, _ = self._device_kwargs()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MfaTotpDevice.objects.create(**second_values)

    def test_full_clean_rejects_malformed_encryption_metadata(self):
        values, _ = self._device_kwargs(
            secret_nonce=b"short",
            secret_ciphertext=b"short",
            key_id="bad key id",
        )
        device = MfaTotpDevice(**values)
        with self.assertRaises(ValidationError) as context:
            device.full_clean()
        self.assertEqual(
            set(context.exception.message_dict),
            {"secret_nonce", "secret_ciphertext", "key_id"},
        )

    def test_database_rejects_inconsistent_status_timestamps(self):
        invalid_cases = (
            {"status": "pending", "confirmed_at": timezone.now()},
            {"status": "active", "confirmed_at": None},
            {"status": "revoked", "revoked_at": None},
        )
        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                values, _ = self._device_kwargs(**overrides)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    MfaTotpDevice.objects.create(**values)

    def test_database_rejects_invalid_replay_and_auth_version_state(self):
        for overrides in ({"auth_version": 0}, {"last_accepted_step": -1}):
            with self.subTest(overrides=overrides):
                values, _ = self._device_kwargs(**overrides)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    MfaTotpDevice.objects.create(**values)

    def test_device_is_not_exposed_in_django_admin(self):
        self.assertNotIn(MfaTotpDevice, admin.site._registry)
        self.assertNotIn(MfaRecoveryCode, admin.site._registry)
