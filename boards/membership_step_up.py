"""One-shot TOTP capabilities for Dashboard Membership mutations."""

import hashlib
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.utils import timezone

from PowerAdapterBlogs.base_admin import has_dashboard_access
from accounts.authn.mfa_services import MfaServiceError, verify_active_totp
from accounts.authn.mfa_session import (
    challenge_is_locked,
    clear_challenge_failures,
    dashboard_session_is_valid,
    record_challenge_failure,
)

MANAGE_MEMBERSHIP_PERMISSION = "boards.manage_all_board_memberships"
STEP_UP_SALT = "boards.membership-step-up.v1"


class MembershipStepUpError(Exception):
    """Public-safe step-up failure with a stable reason code."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__("无法完成板块成员二次验证。")


@dataclass(frozen=True, slots=True)
class MembershipStepUpCapability:
    token: str
    action: str
    target: str


def _ttl_seconds():
    value = getattr(settings, "MEMBERSHIP_STEP_UP_TTL_SECONDS", 300)
    if isinstance(value, bool):
        raise MembershipStepUpError("config_invalid")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise MembershipStepUpError("config_invalid") from exc
    if not 60 <= value <= 300:
        raise MembershipStepUpError("config_invalid")
    return value


def _session_digest(request):
    if request.session.session_key is None:
        request.session.save()
    session_key = request.session.session_key
    if not session_key:
        raise MembershipStepUpError("session_unavailable")
    return hashlib.sha256(session_key.encode("utf-8")).hexdigest()


def _can_manage(user):
    return bool(
        has_dashboard_access(user)
        and user.has_perm(MANAGE_MEMBERSHIP_PERMISSION)
    )


def issue_membership_step_up(*, request, action, target, code):
    """Verify a fresh TOTP step and issue a signed one-shot capability."""
    if not _can_manage(request.user):
        raise MembershipStepUpError("not_allowed")
    if not dashboard_session_is_valid(request):
        raise MembershipStepUpError("privileged_session_required")
    if challenge_is_locked(request, request.user.pk):
        raise MembershipStepUpError("locked")

    try:
        verify_active_totp(
            user=request.user,
            actor=request.user,
            code=code,
        )
    except MfaServiceError as exc:
        record_challenge_failure(request, request.user.pk)
        raise MembershipStepUpError("invalid_code") from exc

    clear_challenge_failures(request, request.user.pk)
    payload = {
        "user_id": request.user.pk,
        "session": _session_digest(request),
        "action": str(action),
        "target": str(target),
        "nonce": secrets.token_urlsafe(24),
        "verified_at": timezone.now().timestamp(),
    }
    token = signing.dumps(payload, salt=STEP_UP_SALT, compress=True)
    return MembershipStepUpCapability(token, str(action), str(target))


def consume_membership_step_up(
    *,
    request,
    capability,
    actor,
    action,
    target,
):
    """Validate bindings and atomically mark one capability as consumed."""
    if actor.pk != request.user.pk or not _can_manage(actor):
        raise MembershipStepUpError("not_allowed")
    if not dashboard_session_is_valid(request):
        raise MembershipStepUpError("privileged_session_required")
    try:
        payload = signing.loads(
            capability.token,
            salt=STEP_UP_SALT,
            max_age=_ttl_seconds(),
        )
    except signing.BadSignature as exc:
        raise MembershipStepUpError("invalid_or_expired") from exc
    expected = {
        "user_id": actor.pk,
        "session": _session_digest(request),
        "action": str(action),
        "target": str(target),
    }
    for key, value in expected.items():
        if not secrets.compare_digest(str(payload.get(key, "")), str(value)):
            raise MembershipStepUpError("binding_mismatch")
    nonce = str(payload.get("nonce", ""))
    if not nonce:
        raise MembershipStepUpError("invalid_or_expired")
    nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    if not cache.add(
        f"membership-step-up:used:{nonce_digest}",
        1,
        timeout=_ttl_seconds(),
    ):
        raise MembershipStepUpError("already_consumed")
    return True
