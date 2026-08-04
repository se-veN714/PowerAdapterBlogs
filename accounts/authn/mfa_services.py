"""H2a TOTP enrollment and recovery services."""

import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

import pyotp
from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from boards.models import BoardMembership
from security.models import SecureLogEntry

from .mfa_crypto import (
    EncryptedMfaSecret,
    MfaCryptoError,
    build_mfa_device_aad,
    decode_keyring,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
)
from ..models import MfaRecoveryCode, MfaTotpDevice, MyUser

GENERIC_MFA_ERROR = "无法完成动态验证码操作。"
RESET_REASONS = frozenset(
    {"operator_reset", "self_reset", "device_lost", "compromised"}
)


class MfaServiceError(Exception):
    """A public-safe failure with a stable internal reason code."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(GENERIC_MFA_ERROR)


@dataclass(frozen=True, slots=True)
class TotpEnrollment:
    device_id: uuid.UUID
    provisioning_uri: str
    expires_at: object


@dataclass(frozen=True, slots=True)
class TotpConfirmation:
    device_id: uuid.UUID
    recovery_codes: tuple[str, ...]


def _keyring():
    try:
        return decode_keyring(settings.MFA_TOTP_KEYRING)
    except (AttributeError, TypeError, MfaCryptoError) as exc:
        raise MfaServiceError("keyring_unavailable") from exc


def _active_key_id() -> str:
    key_id = getattr(settings, "MFA_TOTP_ACTIVE_KEY_ID", "")
    if not isinstance(key_id, str) or not key_id:
        raise MfaServiceError("keyring_unavailable")
    return key_id


def _integer_setting(name: str, *, minimum: int, maximum: int) -> int:
    value = getattr(settings, name, None)
    if isinstance(value, bool):
        raise MfaServiceError("config_invalid")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise MfaServiceError("config_invalid") from exc
    if not minimum <= value <= maximum:
        raise MfaServiceError("config_invalid")
    return value


def _issuer() -> str:
    value = getattr(settings, "MFA_TOTP_ISSUER", "")
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise MfaServiceError("config_invalid")
    return value.strip()


def _is_enrollment_eligible(user: MyUser) -> bool:
    if not user.is_active:
        return False
    if user.is_superuser or user.is_dashboard_user:
        return True
    return BoardMembership.objects.filter(
        user=user,
        role=BoardMembership.Role.MANAGER,
        is_active=True,
    ).exists()


def _require_self_service_actor(*, user: MyUser, actor: MyUser) -> None:
    if actor.pk != user.pk or not _is_enrollment_eligible(user):
        raise MfaServiceError("not_allowed")


def _encrypted_value(device: MfaTotpDevice) -> EncryptedMfaSecret:
    return EncryptedMfaSecret(
        device.key_id,
        bytes(device.secret_nonce),
        bytes(device.secret_ciphertext),
    )


def _aad(device: MfaTotpDevice) -> bytes:
    return build_mfa_device_aad(user_id=device.user_id, device_id=device.pk)


def _decrypt_seed(device: MfaTotpDevice) -> str:
    try:
        plaintext = decrypt_mfa_secret(
            _encrypted_value(device),
            keyring=_keyring(),
            associated_data=_aad(device),
        )
        return plaintext.decode("ascii")
    except (MfaCryptoError, UnicodeDecodeError) as exc:
        raise MfaServiceError("secret_unavailable") from exc


def _audit(*, actor: MyUser, device: MfaTotpDevice, event: str, reason: str = ""):
    """Write a minimal Django LogEntry and require its HMAC companion."""
    content_type = ContentType.objects.get_for_model(MfaTotpDevice)
    message = f"mfa_event={event}"
    if reason:
        message = f"{message};reason={reason}"
    entry = LogEntry.objects.log_action(
        user_id=actor.pk,
        content_type_id=content_type.pk,
        object_id=str(device.pk),
        object_repr=f"TOTP device {device.pk}",
        action_flag=CHANGE,
        change_message=message,
    )
    secure_entry, _ = SecureLogEntry.compute_from_logentry(
        entry,
        settings.LOG_HMAC_KEY,
    )
    return secure_entry


@transaction.atomic
def start_totp_enrollment(*, user: MyUser, actor: MyUser) -> TotpEnrollment:
    """Create or replace one pending encrypted seed and return its URI once."""
    locked_user = MyUser.objects.select_for_update().get(pk=user.pk)
    _require_self_service_actor(user=locked_user, actor=actor)
    keyring = _keyring()
    active_key_id = _active_key_id()
    if active_key_id not in keyring:
        raise MfaServiceError("keyring_unavailable")
    binding_ttl = _integer_setting(
        "MFA_TOTP_BINDING_TTL_SECONDS",
        minimum=60,
        maximum=3600,
    )
    _integer_setting("MFA_TOTP_VALID_WINDOW", minimum=0, maximum=1)
    _integer_setting("MFA_RECOVERY_CODE_COUNT", minimum=10, maximum=10)
    issuer = _issuer()

    device = MfaTotpDevice.objects.select_for_update().filter(user=locked_user).first()
    if device is not None and device.status == MfaTotpDevice.Status.ACTIVE:
        raise MfaServiceError("already_active")
    if device is None:
        device = MfaTotpDevice(id=uuid.uuid4(), user=locked_user)

    seed = pyotp.random_base32()
    expires_at = timezone.now() + timedelta(seconds=binding_ttl)
    encrypted = encrypt_mfa_secret(
        seed.encode("ascii"),
        keyring=keyring,
        active_key_id=active_key_id,
        associated_data=_aad(device),
    )
    device.status = MfaTotpDevice.Status.PENDING
    device.secret_ciphertext = encrypted.ciphertext
    device.secret_nonce = encrypted.nonce
    device.key_id = encrypted.key_id
    device.binding_expires_at = expires_at
    device.confirmed_at = None
    device.revoked_at = None
    device.last_accepted_step = None
    device.full_clean()
    device.save()
    device.recovery_codes.all().delete()
    _audit(actor=actor, device=device, event="enrollment_started")

    uri = pyotp.TOTP(seed).provisioning_uri(
        name=locked_user.username,
        issuer_name=issuer,
    )
    return TotpEnrollment(device.pk, uri, expires_at)


def _matching_step(totp: pyotp.TOTP, code: str, at_time) -> int | None:
    current_step = totp.timecode(at_time)
    window = _integer_setting("MFA_TOTP_VALID_WINDOW", minimum=0, maximum=1)
    for offset in range(-window, window + 1):
        step = current_step + offset
        if step >= 0 and pyotp.utils.strings_equal(totp.generate_otp(step), code):
            return step
    return None


def _new_recovery_codes() -> tuple[str, ...]:
    count = _integer_setting("MFA_RECOVERY_CODE_COUNT", minimum=10, maximum=10)
    return tuple(secrets.token_urlsafe(12) for _ in range(count))


def confirm_totp_enrollment(
    *, user: MyUser, actor: MyUser, code: str
) -> TotpConfirmation:
    """Activate a non-expired pending device exactly once."""
    _require_self_service_actor(user=user, actor=actor)
    failure_reason = ""
    confirmation = None
    with transaction.atomic():
        device = (
            MfaTotpDevice.objects.select_for_update()
            .select_related("user")
            .filter(user=user)
            .first()
        )
        if device is None or device.status != MfaTotpDevice.Status.PENDING:
            raise MfaServiceError("not_pending")
        now = timezone.now()
        if device.binding_expires_at <= now:
            _erase_device_secret(device, revoked_at=now)
            _audit(
                actor=actor,
                device=device,
                event="enrollment_expired",
                reason="binding_expired",
            )
            failure_reason = "binding_expired"
        else:
            try:
                totp = pyotp.TOTP(_decrypt_seed(device))
            except MfaServiceError:
                _erase_device_secret(device, revoked_at=now)
                _audit(
                    actor=actor,
                    device=device,
                    event="enrollment_failed",
                    reason="secret_unavailable",
                )
                failure_reason = "secret_unavailable"
            else:
                matched_step = _matching_step(totp, str(code), now)
                if matched_step is None:
                    _audit(
                        actor=actor,
                        device=device,
                        event="enrollment_failed",
                        reason="invalid_code",
                    )
                    failure_reason = "invalid_code"
                else:
                    recovery_codes = _new_recovery_codes()
                    device.status = MfaTotpDevice.Status.ACTIVE
                    device.confirmed_at = now
                    device.last_accepted_step = matched_step
                    device.full_clean()
                    device.save(
                        update_fields=[
                            "status",
                            "confirmed_at",
                            "last_accepted_step",
                            "updated_at",
                        ]
                    )
                    MfaRecoveryCode.objects.bulk_create(
                        [
                            MfaRecoveryCode(
                                device=device,
                                code_digest=make_password(code_value),
                            )
                            for code_value in recovery_codes
                        ]
                    )
                    _audit(actor=actor, device=device, event="enrollment_confirmed")
                    confirmation = TotpConfirmation(device.pk, recovery_codes)
    if failure_reason:
        raise MfaServiceError(failure_reason)
    return confirmation


@transaction.atomic
def consume_recovery_code(*, user: MyUser, code: str, actor: MyUser) -> bool:
    """Atomically consume one code; success does not create an authenticated session."""
    _require_self_service_actor(user=user, actor=actor)
    device = (
        MfaTotpDevice.objects.select_for_update()
        .filter(user=user, status=MfaTotpDevice.Status.ACTIVE)
        .first()
    )
    if device is None:
        raise MfaServiceError("device_inactive")
    candidates = list(
        MfaRecoveryCode.objects.select_for_update().filter(
            device=device,
            used_at__isnull=True,
        )
    )
    matched = next(
        (
            candidate
            for candidate in candidates
            if check_password(code, candidate.code_digest)
        ),
        None,
    )
    if matched is None:
        _audit(
            actor=actor, device=device, event="recovery_failed", reason="invalid_code"
        )
        return False
    used = MfaRecoveryCode.objects.filter(pk=matched.pk, used_at__isnull=True).update(
        used_at=timezone.now()
    )
    if used != 1:
        return False
    _audit(actor=actor, device=device, event="recovery_consumed")
    return True


@transaction.atomic
def consume_recovery_code_for_rebind(
    *, user: MyUser, code: str, actor: MyUser
) -> MfaTotpDevice | None:
    """Consume one recovery code and erase the old device in one transaction."""
    _require_self_service_actor(user=user, actor=actor)
    device = (
        MfaTotpDevice.objects.select_for_update()
        .filter(user=user, status=MfaTotpDevice.Status.ACTIVE)
        .first()
    )
    if device is None:
        raise MfaServiceError("device_inactive")
    candidates = list(
        MfaRecoveryCode.objects.select_for_update().filter(
            device=device,
            used_at__isnull=True,
        )
    )
    matched = next(
        (
            candidate
            for candidate in candidates
            if check_password(code, candidate.code_digest)
        ),
        None,
    )
    if matched is None:
        _audit(
            actor=actor, device=device, event="recovery_failed", reason="invalid_code"
        )
        return None
    used = MfaRecoveryCode.objects.filter(pk=matched.pk, used_at__isnull=True).update(
        used_at=timezone.now()
    )
    if used != 1:
        return None
    _audit(actor=actor, device=device, event="recovery_consumed")
    _erase_device_secret(device, revoked_at=timezone.now())
    _audit(actor=actor, device=device, event="recovery_rebind_required")
    return device


def verify_active_totp(*, user: MyUser, actor: MyUser, code: str) -> MfaTotpDevice:
    """Verify a fresh TOTP step and update anti-replay state atomically."""
    _require_self_service_actor(user=user, actor=actor)
    failure_reason = ""
    verified_device = None
    with transaction.atomic():
        device = (
            MfaTotpDevice.objects.select_for_update()
            .filter(user=user, status=MfaTotpDevice.Status.ACTIVE)
            .first()
        )
        if device is None:
            raise MfaServiceError("device_inactive")
        matched_step = _matching_step(
            pyotp.TOTP(_decrypt_seed(device)), str(code), timezone.now()
        )
        if matched_step is None:
            failure_reason = "invalid_code"
        elif (
            device.last_accepted_step is not None
            and matched_step <= device.last_accepted_step
        ):
            failure_reason = "replayed_code"
        else:
            device.last_accepted_step = matched_step
            device.save(update_fields=["last_accepted_step", "updated_at"])
            _audit(actor=actor, device=device, event="challenge_verified")
            verified_device = device
        if failure_reason:
            _audit(
                actor=actor,
                device=device,
                event="challenge_failed",
                reason=failure_reason,
            )
    if failure_reason:
        raise MfaServiceError(failure_reason)
    return verified_device


def _can_reset(*, target_user: MyUser, actor: MyUser, current_password: str) -> bool:
    if not actor.is_active or not actor.is_superuser:
        return False
    if actor.pk != target_user.pk:
        return True
    return bool(current_password) and actor.check_password(current_password)


def _erase_device_secret(device: MfaTotpDevice, *, revoked_at) -> None:
    """Destroy decryptability while retaining lifecycle and audit identity."""
    device.status = MfaTotpDevice.Status.REVOKED
    device.revoked_at = revoked_at
    device.last_accepted_step = None
    device.auth_version += 1
    device.secret_nonce = os.urandom(12)
    device.secret_ciphertext = os.urandom(max(17, len(bytes(device.secret_ciphertext))))
    device.full_clean()
    device.save(
        update_fields=[
            "status",
            "revoked_at",
            "last_accepted_step",
            "auth_version",
            "secret_nonce",
            "secret_ciphertext",
            "updated_at",
        ]
    )
    device.recovery_codes.all().delete()


@transaction.atomic
def revoke_totp_device(
    *,
    target_user: MyUser,
    actor: MyUser,
    current_password: str = "",
    totp_code: str = "",
    reason: str = "operator_reset",
) -> MfaTotpDevice:
    """Revoke and cryptographically erase a device under a superuser boundary."""
    if not _can_reset(
        target_user=target_user,
        actor=actor,
        current_password=current_password,
    ):
        raise MfaServiceError("reset_not_allowed")
    device = MfaTotpDevice.objects.select_for_update().filter(user=target_user).first()
    if device is None or device.status == MfaTotpDevice.Status.REVOKED:
        raise MfaServiceError("device_inactive")

    if actor.pk == target_user.pk:
        matched_step = _matching_step(
            pyotp.TOTP(_decrypt_seed(device)),
            str(totp_code),
            timezone.now(),
        )
        if matched_step is None:
            _audit(
                actor=actor,
                device=device,
                event="device_revoke_failed",
                reason="invalid_code",
            )
            raise MfaServiceError("invalid_code")
        if (
            device.last_accepted_step is not None
            and matched_step <= device.last_accepted_step
        ):
            _audit(
                actor=actor,
                device=device,
                event="device_revoke_failed",
                reason="replayed_code",
            )
            raise MfaServiceError("replayed_code")
        _audit(actor=actor, device=device, event="device_revoke_step_up_verified")

    _erase_device_secret(device, revoked_at=timezone.now())
    audit_reason = reason if reason in RESET_REASONS else "operator_reset"
    _audit(actor=actor, device=device, event="device_revoked", reason=audit_reason)
    return device
