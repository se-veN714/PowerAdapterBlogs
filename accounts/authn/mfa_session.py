"""H2b pending-challenge, rate-limit, and privileged-session state."""

import hashlib
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from boards.models import BoardMembership

from ..models import MfaTotpDevice, MyUser

PENDING_KEY = "accounts.mfa.pending"
PRIVILEGED_KEY = "accounts.mfa.privileged"
DASHBOARD_REMEMBER_KEY = "accounts.mfa.dashboard_remember"
RECOVERY_KEY = "accounts.mfa.recovery"
ENROLLMENT_KEY = "accounts.mfa.enrollment"


@dataclass(frozen=True, slots=True)
class PendingMfaChallenge:
    user: MyUser
    backend: str
    target: str
    nonce: str
    issued_at: float
    certificate_binding_id: str | None = None
    certificate_auth_version: int | None = None


def mfa_required_for_user(user) -> bool:
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if user.is_superuser:
        return True
    if user.is_dashboard_user:
        return True
    return BoardMembership.objects.filter(
        user=user,
        role=BoardMembership.Role.MANAGER,
        is_active=True,
    ).exists()


def active_mfa_device(user):
    return MfaTotpDevice.objects.filter(
        user=user,
        status=MfaTotpDevice.Status.ACTIVE,
    ).first()


def _safe_target(request, target: str | None) -> str:
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse("index")


def issue_pending_challenge(
    request,
    *,
    user,
    backend: str,
    target: str | None,
    certificate_binding=None,
):
    value = {
        "user_id": user.pk,
        "backend": backend,
        "target": _safe_target(request, target),
        "nonce": secrets.token_urlsafe(24),
        "issued_at": timezone.now().timestamp(),
        "attempts": 0,
    }
    if certificate_binding is not None:
        value["certificate_binding_id"] = str(certificate_binding.pk)
        value["certificate_auth_version"] = certificate_binding.auth_version
    request.session[PENDING_KEY] = value
    request.session.pop(PRIVILEGED_KEY, None)
    request.session.pop(RECOVERY_KEY, None)
    request.session.pop(ENROLLMENT_KEY, None)


def get_pending_challenge(request) -> PendingMfaChallenge | None:
    value = request.session.get(PENDING_KEY)
    if not isinstance(value, dict):
        return None
    try:
        issued_at = float(value["issued_at"])
        user_id = int(value["user_id"])
        backend = str(value["backend"])
        target = str(value["target"])
        nonce = str(value["nonce"])
    except (KeyError, TypeError, ValueError):
        clear_pending_challenge(request)
        return None
    age = timezone.now().timestamp() - issued_at
    if age < 0 or age > settings.MFA_CHALLENGE_TTL_SECONDS:
        clear_pending_challenge(request)
        return None
    user = MyUser.objects.filter(pk=user_id, is_active=True).first()
    if (
        user is None
        or not mfa_required_for_user(user)
        or active_mfa_device(user) is None
    ):
        clear_pending_challenge(request)
        return None
    binding_id = value.get("certificate_binding_id")
    binding_version = value.get("certificate_auth_version")
    if (binding_id is None) != (binding_version is None):
        clear_pending_challenge(request)
        return None
    if binding_id is not None:
        try:
            binding_id = str(binding_id)
            binding_version = int(binding_version)
        except (TypeError, ValueError):
            clear_pending_challenge(request)
            return None
    return PendingMfaChallenge(
        user,
        backend,
        target,
        nonce,
        issued_at,
        binding_id,
        binding_version,
    )


def clear_pending_challenge(request):
    request.session.pop(PENDING_KEY, None)


def increment_pending_attempts(request) -> int:
    value = request.session.get(PENDING_KEY)
    if not isinstance(value, dict):
        return settings.MFA_CHALLENGE_MAX_ATTEMPTS
    value["attempts"] = int(value.get("attempts", 0)) + 1
    request.session[PENDING_KEY] = value
    return value["attempts"]


def _client_identity(request) -> str:
    return str(
        getattr(request, "client_ip", request.META.get("REMOTE_ADDR", "unknown"))
    )


def _rate_key(kind: str, *, user_id: int, client: str = "") -> str:
    digest = hashlib.sha256(f"{user_id}|{client}".encode("utf-8")).hexdigest()
    return f"mfa-challenge:{kind}:{digest}"


def challenge_is_locked(request, user_id: int) -> bool:
    client = _client_identity(request)
    return bool(
        cache.get(_rate_key("lock-user", user_id=user_id))
        or cache.get(_rate_key("lock-pair", user_id=user_id, client=client))
    )


def record_challenge_failure(request, user_id: int) -> int:
    client = _client_identity(request)
    timeout = settings.MFA_CHALLENGE_COOLDOWN_SECONDS
    counts = []
    for kind, identity in (("count-user", ""), ("count-pair", client)):
        key = _rate_key(kind, user_id=user_id, client=identity)
        if cache.add(key, 1, timeout=timeout):
            counts.append(1)
        else:
            try:
                counts.append(cache.incr(key))
            except ValueError:
                cache.set(key, 1, timeout=timeout)
                counts.append(1)
    attempts = max(counts)
    if attempts >= settings.MFA_CHALLENGE_MAX_ATTEMPTS:
        cache.set(_rate_key("lock-user", user_id=user_id), 1, timeout=timeout)
        cache.set(
            _rate_key("lock-pair", user_id=user_id, client=client),
            1,
            timeout=timeout,
        )
    return attempts


def clear_challenge_failures(request, user_id: int):
    client = _client_identity(request)
    cache.delete_many(
        (
            _rate_key("count-user", user_id=user_id),
            _rate_key("count-pair", user_id=user_id, client=client),
            _rate_key("lock-user", user_id=user_id),
            _rate_key("lock-pair", user_id=user_id, client=client),
        )
    )


def mark_privileged_session(
    request,
    device: MfaTotpDevice,
    certificate_binding=None,
    *,
    remember_dashboard: bool | None = None,
):
    now = timezone.now().timestamp()
    value = {
        "user_id": device.user_id,
        "device_id": str(device.pk),
        "auth_version": device.auth_version,
        "verified_at": now,
    }
    if certificate_binding is not None:
        value["certificate_binding_id"] = str(certificate_binding.pk)
        value["certificate_auth_version"] = certificate_binding.auth_version
        value["last_seen_at"] = now
        # The admin host uses its own host-only cookie. Keep its authenticated
        # session browser-scoped without shortening the dashboard session.
        request.session.set_expiry(0)
    request.session[PRIVILEGED_KEY] = value
    if remember_dashboard is not None:
        if remember_dashboard and certificate_binding is None:
            request.session[DASHBOARD_REMEMBER_KEY] = {
                **value,
                "expires_at": now + settings.MFA_DASHBOARD_REMEMBER_TTL_SECONDS,
            }
        else:
            request.session.pop(DASHBOARD_REMEMBER_KEY, None)
    request.session.pop(PENDING_KEY, None)
    request.session.pop(RECOVERY_KEY, None)
    request.session.pop(ENROLLMENT_KEY, None)


def privileged_session_is_valid(request, *, require_certificate: bool = False) -> bool:
    value = request.session.get(PRIVILEGED_KEY)
    if not isinstance(value, dict) or not request.user.is_authenticated:
        return False
    try:
        now = timezone.now().timestamp()
        verified_at = float(value["verified_at"])
        age = now - verified_at
        user_id = int(value["user_id"])
        device_id = str(value["device_id"])
        auth_version = int(value["auth_version"])
    except (KeyError, TypeError, ValueError):
        request.session.pop(PRIVILEGED_KEY, None)
        return False
    if age < 0 or age > settings.MFA_PRIVILEGED_SESSION_TTL_SECONDS:
        request.session.pop(PRIVILEGED_KEY, None)
        return False
    valid = MfaTotpDevice.objects.filter(
        pk=device_id,
        user_id=user_id,
        user=request.user,
        status=MfaTotpDevice.Status.ACTIVE,
        auth_version=auth_version,
    ).exists()
    certificate_binding_id = value.get("certificate_binding_id")
    certificate_auth_version = value.get("certificate_auth_version")
    if require_certificate and certificate_binding_id is None:
        valid = False
    if (certificate_binding_id is None) != (certificate_auth_version is None):
        valid = False
    elif certificate_binding_id is not None:
        from ..models import ClientCertificateBinding

        try:
            certificate_auth_version = int(certificate_auth_version)
        except (TypeError, ValueError):
            valid = False
        else:
            valid = (
                valid
                and ClientCertificateBinding.objects.filter(
                    pk=certificate_binding_id,
                    user=request.user,
                    status=ClientCertificateBinding.Status.ACTIVE,
                    auth_version=certificate_auth_version,
                    expires_at__gt=timezone.now(),
                ).exists()
            )
            presented_binding = getattr(
                request,
                "client_certificate_binding",
                None,
            )
            if presented_binding is not None:
                valid = valid and str(presented_binding.pk) == str(
                    certificate_binding_id
                )
    if valid and require_certificate:
        try:
            last_seen_at = float(value.get("last_seen_at", verified_at))
        except (TypeError, ValueError):
            valid = False
        else:
            idle_age = now - last_seen_at
            valid = 0 <= idle_age <= settings.MFA_SUPER_ADMIN_IDLE_TTL_SECONDS
            if valid:
                value["last_seen_at"] = now
                request.session[PRIVILEGED_KEY] = value
    if not valid:
        request.session.pop(PRIVILEGED_KEY, None)
    return valid


def dashboard_remembered_session_is_valid(request) -> bool:
    """Validate the optional seven-day grant only for the daily dashboard."""

    value = request.session.get(DASHBOARD_REMEMBER_KEY)
    if not isinstance(value, dict) or not request.user.is_authenticated:
        return False
    try:
        now = timezone.now().timestamp()
        verified_at = float(value["verified_at"])
        expires_at = float(value["expires_at"])
        user_id = int(value["user_id"])
        device_id = str(value["device_id"])
        auth_version = int(value["auth_version"])
    except (KeyError, TypeError, ValueError):
        request.session.pop(DASHBOARD_REMEMBER_KEY, None)
        return False
    max_ttl = settings.MFA_DASHBOARD_REMEMBER_TTL_SECONDS
    valid = (
        0 <= now - verified_at <= max_ttl
        and now <= expires_at <= verified_at + max_ttl
        and request.user.pk == user_id
        and (request.user.is_dashboard_user or request.user.is_superuser)
        and MfaTotpDevice.objects.filter(
            pk=device_id,
            user_id=user_id,
            status=MfaTotpDevice.Status.ACTIVE,
            auth_version=auth_version,
        ).exists()
    )
    if not valid:
        request.session.pop(DASHBOARD_REMEMBER_KEY, None)
    return valid


def dashboard_session_is_valid(request) -> bool:
    """Accept a fresh TOTP session or the dashboard-only remembered grant."""

    return privileged_session_is_valid(
        request,
    ) or dashboard_remembered_session_is_valid(request)


def mark_recovery_session(request, device: MfaTotpDevice):
    request.session[RECOVERY_KEY] = {
        "user_id": device.user_id,
        "auth_version": device.auth_version,
        "issued_at": timezone.now().timestamp(),
    }
    request.session.pop(PENDING_KEY, None)
    request.session.pop(PRIVILEGED_KEY, None)
    request.session.pop(ENROLLMENT_KEY, None)


def mark_enrollment_session(request, user: MyUser):
    """Confine a password-authenticated privileged user to initial MFA setup."""

    request.session[ENROLLMENT_KEY] = {
        "user_id": user.pk,
        "issued_at": timezone.now().timestamp(),
    }
    request.session.pop(PENDING_KEY, None)
    request.session.pop(PRIVILEGED_KEY, None)
    request.session.pop(RECOVERY_KEY, None)


def enrollment_session_is_valid(request) -> bool:
    value = request.session.get(ENROLLMENT_KEY)
    if not isinstance(value, dict) or not request.user.is_authenticated:
        return False
    try:
        age = timezone.now().timestamp() - float(value["issued_at"])
        user_id = int(value["user_id"])
    except (KeyError, TypeError, ValueError):
        request.session.pop(ENROLLMENT_KEY, None)
        return False
    valid = (
        0 <= age <= settings.MFA_TOTP_BINDING_TTL_SECONDS
        and request.user.pk == user_id
        and mfa_required_for_user(request.user)
        and active_mfa_device(request.user) is None
    )
    if not valid:
        request.session.pop(ENROLLMENT_KEY, None)
    return valid


def recovery_session_is_valid(request) -> bool:
    value = request.session.get(RECOVERY_KEY)
    if not isinstance(value, dict) or not request.user.is_authenticated:
        return False
    try:
        age = timezone.now().timestamp() - float(value["issued_at"])
        user_id = int(value["user_id"])
        auth_version = int(value["auth_version"])
    except (KeyError, TypeError, ValueError):
        request.session.pop(RECOVERY_KEY, None)
        return False
    valid = (
        0 <= age <= settings.MFA_CHALLENGE_TTL_SECONDS
        and request.user.pk == user_id
        and MfaTotpDevice.objects.filter(
            user_id=user_id,
            status=MfaTotpDevice.Status.REVOKED,
            auth_version=auth_version,
        ).exists()
    )
    if not valid:
        request.session.pop(RECOVERY_KEY, None)
    return valid
