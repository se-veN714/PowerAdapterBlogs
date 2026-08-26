"""H3 trusted-proxy contract and client-certificate lifecycle services."""

import ipaddress
import logging
import re
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.core.exceptions import DisallowedHost
from django.utils import timezone

from security.outbox import enqueue_audit_event
from security.sec_utils.hmac_utils import sm3_digest

from ..models import ClientCertificateBinding, MyUser

logger = logging.getLogger(__name__)

VERIFY_HEADER = "HTTP_X_PA_MTLS_VERIFY"
SERIAL_HEADER = "HTTP_X_PA_MTLS_SERIAL"
ISSUER_HEADER = "HTTP_X_PA_MTLS_ISSUER_DN"
SUBJECT_HEADER = "HTTP_X_PA_MTLS_SUBJECT_DN"
PROXY_AUTH_HEADER = "HTTP_X_PA_PROXY_AUTH"
PROFILE_HEADER = "HTTP_X_PA_MTLS_PROFILE"
_SERIAL_PATTERN = re.compile(r"^[0-9A-F]{1,128}$")
PRODUCTION_CERTIFICATE_PROFILE = ClientCertificateBinding.Profile.STANDARD_TLS


class MtlsServiceError(Exception):
    """Fail-closed mTLS request or lifecycle error with a non-secret reason."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class PresentedCertificate:
    serial_number: str
    issuer_dn: str
    subject_dn: str
    certificate_profile: str


def _clean_dn(value, *, reason: str) -> str:
    if not isinstance(value, str):
        raise MtlsServiceError(reason)
    value = value.strip()
    if not value or len(value) > 2048:
        raise MtlsServiceError(reason)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise MtlsServiceError(reason)
    return value


def normalize_certificate_serial(value) -> str:
    if not isinstance(value, str):
        raise MtlsServiceError("invalid_serial")
    normalized = value.replace(":", "").replace(" ", "").upper()
    if not _SERIAL_PATTERN.fullmatch(normalized):
        raise MtlsServiceError("invalid_serial")
    return normalized


def issuer_dn_digest(issuer_dn: str) -> str:
    normalized = _clean_dn(issuer_dn, reason="invalid_issuer")
    return sm3_digest(normalized.encode("utf-8"))


def _configured_proxy_networks():
    networks = getattr(settings, "MTLS_TRUSTED_PROXY_NETWORKS", ())
    if not isinstance(networks, (tuple, list)) or not networks:
        raise MtlsServiceError("proxy_config_invalid")
    try:
        return tuple(ipaddress.ip_network(value, strict=False) for value in networks)
    except (TypeError, ValueError) as exc:
        raise MtlsServiceError("proxy_config_invalid") from exc


def _trusted_transport(request) -> None:
    expected_host = getattr(settings, "MTLS_ADMIN_HOST", "")
    proxy_secret = getattr(settings, "MTLS_PROXY_AUTH_SECRET", "")
    if (
        not isinstance(expected_host, str)
        or not expected_host.strip()
        or not isinstance(proxy_secret, str)
        or len(proxy_secret) < 32
    ):
        raise MtlsServiceError("proxy_config_invalid")
    try:
        request_host = request.get_host().partition(":")[0].casefold()
    except DisallowedHost as exc:
        raise MtlsServiceError("wrong_admin_host") from exc
    if request_host != expected_host.casefold():
        raise MtlsServiceError("wrong_admin_host")
    remote_value = request.META.get("REMOTE_ADDR", "")
    trust_unix_socket = getattr(settings, "MTLS_TRUST_UNIX_SOCKET_PROXY", False)
    if not remote_value and trust_unix_socket is True:
        remote_address = None
    else:
        try:
            remote_address = ipaddress.ip_address(remote_value)
        except ValueError as exc:
            raise MtlsServiceError("untrusted_proxy") from exc
        if not any(
            remote_address in network for network in _configured_proxy_networks()
        ):
            raise MtlsServiceError("untrusted_proxy")
    presented_secret = request.META.get(PROXY_AUTH_HEADER, "")
    if not isinstance(presented_secret, str) or not secrets.compare_digest(
        presented_secret,
        proxy_secret,
    ):
        raise MtlsServiceError("untrusted_proxy")


def presented_certificate_from_request(request) -> PresentedCertificate:
    """Accept certificate metadata only across the configured proxy boundary."""
    _trusted_transport(request)
    if request.META.get(VERIFY_HEADER) != "SUCCESS":
        raise MtlsServiceError("certificate_unverified")
    profile = request.META.get(PROFILE_HEADER)
    expected_profile = getattr(settings, "MTLS_CERTIFICATE_PROFILE", "")
    if (
        not isinstance(expected_profile, str)
        or expected_profile != PRODUCTION_CERTIFICATE_PROFILE
        or profile != expected_profile
    ):
        raise MtlsServiceError("certificate_profile_mismatch")
    return PresentedCertificate(
        serial_number=normalize_certificate_serial(request.META.get(SERIAL_HEADER)),
        issuer_dn=_clean_dn(
            request.META.get(ISSUER_HEADER),
            reason="invalid_issuer",
        ),
        subject_dn=_clean_dn(
            request.META.get(SUBJECT_HEADER),
            reason="invalid_subject",
        ),
        certificate_profile=profile,
    )


def resolve_client_certificate(request, *, expected_user=None):
    presented = presented_certificate_from_request(request)
    binding = (
        ClientCertificateBinding.objects.select_related("user")
        .filter(
            serial_number=presented.serial_number,
            issuer_dn_sm3=issuer_dn_digest(presented.issuer_dn),
            certificate_profile=presented.certificate_profile,
            status=ClientCertificateBinding.Status.ACTIVE,
            expires_at__gt=timezone.now(),
            user__is_active=True,
            user__is_superuser=True,
        )
        .first()
    )
    if binding is None:
        raise MtlsServiceError("binding_not_found")
    if not secrets.compare_digest(binding.issuer_dn, presented.issuer_dn):
        raise MtlsServiceError("binding_mismatch")
    if not secrets.compare_digest(binding.subject_dn, presented.subject_dn):
        raise MtlsServiceError("binding_mismatch")
    if expected_user is not None and binding.user_id != expected_user.pk:
        raise MtlsServiceError("user_mismatch")
    return binding


def _audit(*, actor, binding, event: str, reason: str = ""):
    reason_code = str(reason or "NONE").strip().lower()
    if reason_code not in {
        "none",
        "rotated",
        "expired",
        "compromised",
        "operator_reset",
    }:
        reason_code = "other"
    return enqueue_audit_event(
        event_type=f"mtls.{event}",
        actor={"type": "user", "id": str(actor.pk)},
        target={"type": "client_certificate_binding", "id": str(binding.pk)},
        context={"source": "mtls-service"},
        change={
            "after": {
                "status": binding.status,
                "auth_version": int(binding.auth_version),
                "certificate_profile": binding.certificate_profile,
                "reason_code": reason_code.upper(),
            }
        },
        outcome={"status": "success", "error_code": None},
    )


@transaction.atomic
def bind_client_certificate(
    *,
    user: MyUser,
    actor: MyUser,
    serial_number: str,
    issuer_dn: str,
    subject_dn: str,
    certificate_profile: str,
    expires_at,
):
    if not actor.is_active or not actor.is_superuser:
        raise MtlsServiceError("not_allowed")
    target = MyUser.objects.select_for_update().filter(pk=user.pk).first()
    if target is None or not target.is_active or not target.is_superuser:
        raise MtlsServiceError("target_not_allowed")
    if timezone.is_naive(expires_at) or expires_at <= timezone.now():
        raise MtlsServiceError("invalid_expiry")
    serial_number = normalize_certificate_serial(serial_number)
    issuer_dn = _clean_dn(issuer_dn, reason="invalid_issuer")
    subject_dn = _clean_dn(subject_dn, reason="invalid_subject")
    valid_profiles = {
        choice for choice, _label in ClientCertificateBinding.Profile.choices
    }
    if certificate_profile not in valid_profiles:
        raise MtlsServiceError("invalid_certificate_profile")
    try:
        binding = ClientCertificateBinding.objects.create(
            user=target,
            serial_number=serial_number,
            issuer_dn=issuer_dn,
            issuer_dn_sm3=issuer_dn_digest(issuer_dn),
            subject_dn=subject_dn,
            certificate_profile=certificate_profile,
            expires_at=expires_at,
            verified_at=timezone.now(),
        )
    except IntegrityError as exc:
        raise MtlsServiceError("certificate_already_bound") from exc
    _audit(actor=actor, binding=binding, event="certificate_bound")
    return binding


@transaction.atomic
def revoke_client_certificate(*, binding, actor: MyUser, reason: str):
    if not actor.is_active or not actor.is_superuser:
        raise MtlsServiceError("not_allowed")
    locked = ClientCertificateBinding.objects.select_for_update().get(pk=binding.pk)
    if locked.status != ClientCertificateBinding.Status.ACTIVE:
        raise MtlsServiceError("already_revoked")
    locked.status = ClientCertificateBinding.Status.REVOKED
    locked.revoked_at = timezone.now()
    locked.auth_version += 1
    locked.save(update_fields=("status", "revoked_at", "auth_version", "updated_at"))
    _audit(
        actor=actor,
        binding=locked,
        event="certificate_revoked",
        reason=reason,
    )
    return locked


def log_request_rejection(reason: str):
    """Log only an enumerated reason; never reflect certificate headers."""
    logger.warning("mTLS request rejected: reason=%s", reason)
