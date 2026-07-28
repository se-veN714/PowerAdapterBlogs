import base64
import os
from dataclasses import replace

from django.test import SimpleTestCase

from accounts.mfa_crypto import (
    AES_256_KEY_BYTES,
    MfaCryptoError,
    decode_keyring,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
)


class MfaSecretEncryptionTest(SimpleTestCase):
    def setUp(self):
        self.key = os.urandom(AES_256_KEY_BYTES)
        self.keyring = {"test-v1": self.key}
        self.secret = os.urandom(20)
        self.aad = b"accounts:mfa-device:test-user:test-device"

    def encrypt(self):
        return encrypt_mfa_secret(
            self.secret,
            keyring=self.keyring,
            active_key_id="test-v1",
            associated_data=self.aad,
        )

    def test_seed_is_encrypted_before_any_persistence_boundary(self):
        encrypted = self.encrypt()

        self.assertNotIn(self.secret, encrypted.ciphertext)
        self.assertEqual(encrypted.key_id, "test-v1")
        self.assertEqual(
            decrypt_mfa_secret(
                encrypted,
                keyring=self.keyring,
                associated_data=self.aad,
            ),
            self.secret,
        )

    def test_each_encryption_uses_a_fresh_nonce(self):
        first = self.encrypt()
        second = self.encrypt()

        self.assertNotEqual(first.nonce, second.nonce)
        self.assertNotEqual(first.ciphertext, second.ciphertext)

    def test_ciphertext_or_associated_data_tampering_fails_closed(self):
        encrypted = self.encrypt()
        tampered = replace(
            encrypted,
            ciphertext=encrypted.ciphertext[:-1]
            + bytes([encrypted.ciphertext[-1] ^ 1]),
        )

        for value, aad in ((tampered, self.aad), (encrypted, b"wrong-device")):
            with self.subTest(aad=aad):
                with self.assertRaisesMessage(
                    MfaCryptoError,
                    "MFA secret decryption failed.",
                ):
                    decrypt_mfa_secret(
                        value,
                        keyring=self.keyring,
                        associated_data=aad,
                    )

    def test_unknown_or_malformed_keys_fail_without_sensitive_details(self):
        encrypted = self.encrypt()

        with self.assertRaisesMessage(MfaCryptoError, "key is unavailable"):
            decrypt_mfa_secret(
                replace(encrypted, key_id="missing"),
                keyring=self.keyring,
                associated_data=self.aad,
            )
        with self.assertRaisesMessage(MfaCryptoError, "key is unavailable"):
            encrypt_mfa_secret(
                self.secret,
                keyring={"test-v1": b"short"},
                active_key_id="test-v1",
                associated_data=self.aad,
            )

    def test_keyring_accepts_only_versioned_aes_256_keys(self):
        encoded = base64.urlsafe_b64encode(self.key).decode("ascii")

        decoded = decode_keyring({"test-v1": encoded})

        self.assertEqual(decoded["test-v1"], self.key)
        for invalid in (
            {"test-v1": "not-base64"},
            {"bad\nkey-id": encoded},
            {"test-v1": None},
            {1: encoded},
            {"test-v1": 123},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesMessage(
                    MfaCryptoError,
                    "configuration is invalid",
                ):
                    decode_keyring(invalid)
