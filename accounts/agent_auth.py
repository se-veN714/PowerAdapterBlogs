from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from padif.permissions import can_use_padif
from security.outbox import enqueue_audit_event

from .models import AgentAccessToken, AgentDeviceAuthorization, MyUser

AGENT_SCOPE_PADIF_READ = "padif:read"
AGENT_SCOPE_PADIF_ANNOTATE = "padif:annotate"
AGENT_SCOPE_PADIF_VERSION = "padif:version"
AGENT_SCOPES = {
    AGENT_SCOPE_PADIF_READ,
    AGENT_SCOPE_PADIF_ANNOTATE,
    AGENT_SCOPE_PADIF_VERSION,
}


def _audit_actor(user: MyUser | None) -> dict[str, str]:
    if user is not None and getattr(user, "is_authenticated", False):
        return {"type": "user", "id": str(user.pk)}
    return {"type": "system", "id": "system"}


def _audit_agent_event(*, event_type: str, actor: MyUser | None, target_type: str, target_id: int, change: dict, source: str) -> None:
    enqueue_audit_event(
        event_type=event_type,
        actor=_audit_actor(actor),
        target={"type": target_type, "id": str(target_id)},
        context={"source": source},
        change=change,
        outcome={"status": "success", "error_code": None},
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_agent_scopes(scopes: list[str] | None) -> list[str]:
    requested = [AGENT_SCOPE_PADIF_READ] if scopes is None else scopes
    if not isinstance(requested, list) or not requested or any(scope not in AGENT_SCOPES for scope in requested):
        raise ValueError("unsupported_scope")
    return list(dict.fromkeys(requested))


@transaction.atomic
def create_device_authorization(*, client_name: str, scopes: list[str] | None = None) -> dict[str, object]:
    normalized_scopes = normalize_agent_scopes(scopes)
    device_code = secrets.token_urlsafe(36)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    user_code = "-".join(
        "".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2)
    )
    expires_in = getattr(settings, "AGENT_DEVICE_CODE_TTL_SECONDS", 600)
    authorization = AgentDeviceAuthorization.objects.create(
        client_name=client_name.strip()[:120] or "Unnamed Agent",
        device_code_digest=_digest(device_code),
        user_code_digest=_digest(user_code.replace("-", "")),
        scopes=normalized_scopes,
        expires_at=timezone.now() + timedelta(seconds=expires_in),
    )
    _audit_agent_event(
        event_type="agent.authorization.requested",
        actor=None,
        target_type="agent_device_authorization",
        target_id=authorization.pk,
        change={"client_name": authorization.client_name, "scopes": normalized_scopes},
        source="device_flow",
    )
    return {
        "authorization": authorization,
        "device_code": device_code,
        "user_code": user_code,
        "expires_in": expires_in,
        "interval": getattr(settings, "AGENT_DEVICE_POLL_INTERVAL_SECONDS", 5),
        "scopes": normalized_scopes,
    }


def get_pending_authorization(user_code: str) -> AgentDeviceAuthorization | None:
    return (
        AgentDeviceAuthorization.objects.select_related("user")
        .filter(
            user_code_digest=_digest(user_code.replace("-", "").upper()),
            status=AgentDeviceAuthorization.Status.PENDING,
            expires_at__gt=timezone.now(),
        )
        .first()
    )


def approve_device_authorization(*, user: MyUser, user_code: str, approve: bool) -> AgentDeviceAuthorization | None:
    with transaction.atomic():
        authorization = (
            AgentDeviceAuthorization.objects.select_for_update()
            .filter(
                user_code_digest=_digest(user_code.replace("-", "").upper()),
                status=AgentDeviceAuthorization.Status.PENDING,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        if authorization is None:
            return None
        if any(scope.startswith("padif:") for scope in authorization.scopes) and not can_use_padif(user):
            raise PermissionError("padif_access_denied")
        now = timezone.now()
        authorization.user = user
        authorization.status = (
            AgentDeviceAuthorization.Status.APPROVED
            if approve
            else AgentDeviceAuthorization.Status.DENIED
        )
        authorization.approved_at = now if approve else None
        authorization.denied_at = None if approve else now
        authorization.save(update_fields=("user", "status", "approved_at", "denied_at"))
        _audit_agent_event(
            event_type=(
                "agent.authorization.approved"
                if approve
                else "agent.authorization.denied"
            ),
            actor=user,
            target_type="agent_device_authorization",
            target_id=authorization.pk,
            change={"status": authorization.status, "scopes": authorization.scopes},
            source="web",
        )
        return authorization


def issue_access_token(*, authorization: AgentDeviceAuthorization, device_code: str) -> dict[str, object] | None:
    with transaction.atomic():
        locked = AgentDeviceAuthorization.objects.select_for_update().get(pk=authorization.pk)
        if locked.status != AgentDeviceAuthorization.Status.APPROVED or locked.consumed_at is not None:
            return None
        if locked.expires_at <= timezone.now() or locked.user is None:
            return None
        token = secrets.token_urlsafe(48)
        expires_in = getattr(settings, "AGENT_ACCESS_TOKEN_TTL_SECONDS", 900)
        now = timezone.now()
        locked.status = AgentDeviceAuthorization.Status.CONSUMED
        locked.consumed_at = now
        locked.save(update_fields=("status", "consumed_at"))
        access_token = AgentAccessToken.objects.create(
            authorization=locked,
            user=locked.user,
            token_digest=_digest(token),
            scopes=locked.scopes,
            expires_at=now + timedelta(seconds=expires_in),
        )
        _audit_agent_event(
            event_type="agent.token.issued",
            actor=locked.user,
            target_type="agent_access_token",
            target_id=access_token.pk,
            change={"status": "issued", "scopes": locked.scopes},
            source="device_flow",
        )
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "scope": " ".join(locked.scopes),
        }


def authenticate_agent_token(token: str, required_scope: str | None = None) -> tuple[AgentAccessToken | None, str | None]:
    candidate = (
        AgentAccessToken.objects.select_related("user")
        .filter(token_digest=_digest(token), revoked_at__isnull=True, expires_at__gt=timezone.now())
        .first()
    )
    if candidate is None or not candidate.user.is_active:
        return None, "invalid_token"
    if required_scope and required_scope not in candidate.scopes:
        return None, "insufficient_scope"
    candidate.last_used_at = timezone.now()
    candidate.save(update_fields=("last_used_at",))
    return candidate, None


@transaction.atomic
def revoke_agent_access_tokens(
    *,
    token_ids,
    actor: MyUser,
    source: str,
    event_type: str = "agent.token.revoked",
    reason: str = "manual_revoke",
) -> int:
    tokens = list(
        AgentAccessToken.objects.select_for_update()
        .filter(pk__in=token_ids, revoked_at__isnull=True)
    )
    now = timezone.now()
    for token in tokens:
        token.revoked_at = now
        token.save(update_fields=("revoked_at",))
        _audit_agent_event(
            event_type=event_type,
            actor=actor,
            target_type="agent_access_token",
            target_id=token.pk,
            change={"status": "revoked", "reason_code": reason},
            source=source,
        )
    return len(tokens)


def revoke_agent_access_token(
    *,
    token_id: int,
    actor: MyUser,
    source: str,
    event_type: str = "agent.token.revoked",
    reason: str = "manual_revoke",
) -> bool:
    return bool(
        revoke_agent_access_tokens(
            token_ids=[token_id],
            actor=actor,
            source=source,
            event_type=event_type,
            reason=reason,
        )
    )
