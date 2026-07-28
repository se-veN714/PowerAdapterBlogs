"""Small, persistence-agnostic encryption boundary for TOTP seeds."""

import base64
import binascii
import os
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AES_256_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12


class MfaCryptoError(Exception):
    """Fail-closed error that never exposes key, ciphertext, or plaintext."""


@dataclass(frozen=True, slots=True)
class EncryptedMfaSecret:
    key_id: str
    nonce: bytes
    ciphertext: bytes


def build_mfa_device_aad(*, user_id: int, device_id: object) -> bytes:
    """Bind ciphertext to exactly one user and one pre-generated device UUID."""
    if not isinstance(user_id, int) or user_id < 1 or device_id is None:
        raise MfaCryptoError("MFA associated data is invalid.")
    return f"accounts:mfa-totp-device:v1:{user_id}:{device_id}".encode("ascii")


def decode_keyring(encoded_keys: Mapping[str, str]) -> Mapping[str, bytes]:
    """Decode a versioned URL-safe Base64 keyring from deployment settings."""
    decoded = {}
    for key_id, encoded_key in encoded_keys.items():
        if (
            not isinstance(key_id, str)
            or not isinstance(encoded_key, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", key_id)
        ):
            raise MfaCryptoError("MFA encryption key configuration is invalid.")
        try:
            key = base64.b64decode(encoded_key, altchars=b"-_", validate=True)
        except (TypeError, ValueError, binascii.Error) as exc:
            raise MfaCryptoError(
                "MFA encryption key configuration is invalid."
            ) from exc
        if len(key) != AES_256_KEY_BYTES:
            raise MfaCryptoError("MFA encryption key configuration is invalid.")
        decoded[key_id] = key
    if not decoded:
        raise MfaCryptoError("MFA encryption key configuration is invalid.")
    return MappingProxyType(decoded)


def encrypt_mfa_secret(
    plaintext: bytes,
    *,
    keyring: Mapping[str, bytes],
    active_key_id: str,
    associated_data: bytes,
) -> EncryptedMfaSecret:
    """Encrypt one seed with AES-256-GCM and a fresh 96-bit nonce."""
    key = _get_key(keyring, active_key_id)
    if not plaintext or not associated_data:
        raise MfaCryptoError("MFA secret encryption input is invalid.")
    nonce = os.urandom(AES_GCM_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data)
    return EncryptedMfaSecret(active_key_id, nonce, ciphertext)


def decrypt_mfa_secret(
    encrypted: EncryptedMfaSecret,
    *,
    keyring: Mapping[str, bytes],
    associated_data: bytes,
) -> bytes:
    """Decrypt and authenticate one seed, returning only a generic failure."""
    key = _get_key(keyring, encrypted.key_id)
    if len(encrypted.nonce) != AES_GCM_NONCE_BYTES or not associated_data:
        raise MfaCryptoError("MFA secret decryption failed.")
    try:
        return AESGCM(key).decrypt(
            encrypted.nonce,
            encrypted.ciphertext,
            associated_data,
        )
    except (InvalidTag, ValueError) as exc:
        raise MfaCryptoError("MFA secret decryption failed.") from exc


def _get_key(keyring: Mapping[str, bytes], key_id: str) -> bytes:
    key = keyring.get(key_id)
    if key is None or len(key) != AES_256_KEY_BYTES:
        raise MfaCryptoError("MFA encryption key is unavailable.")
    return key
