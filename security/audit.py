"""Canonical, versioned HMAC-SM3 audit-event primitives."""

from __future__ import annotations

import hmac
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

from django.conf import settings

from security.sec_utils.hmac_utils import sm3_hmac


SCHEMA_VERSION = 1
ALGORITHM = "HMAC-SM3"
IMMUTABLE_EVENT_FIELDS = (
    "schema_version",
    "event_id",
    "event_type",
    "occurred_at",
    "actor",
    "target",
    "context",
    "change",
    "outcome",
)
PUBLIC_EVENT_FIELDS = ("_id", *IMMUTABLE_EVENT_FIELDS, "ingested_at", "integrity")
REQUIRED_EVENT_FIELDS = frozenset(PUBLIC_EVENT_FIELDS)
REQUIRED_INTEGRITY_FIELDS = frozenset(
    {"algorithm", "key_id", "partition", "sequence", "previous_mac", "mac"}
)


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TypeError("audit timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise TypeError("floating-point values are not allowed in canonical audit JSON")
    if isinstance(value, datetime):
        return _utc_timestamp(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical audit JSON object keys must be strings")
        return {key: _normalize(item) for key, item in value.items()}
    raise TypeError(f"unsupported canonical audit value: {type(value).__name__}")


def canonical_json_bytes(value: Any, *, legacy: bool = False) -> bytes:
    """Encode allow-listed values deterministically; legacy preserves v0 bytes."""
    if legacy:
        return json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class AuditKeyring:
    domain: str
    active_key_id: str
    keys: Mapping[str, bytes]
    legacy_key_id: str | None = None

    def __post_init__(self):
        if not self.domain:
            raise ValueError("audit key domain is required")
        for key_id, key in self.keys.items():
            if not key_id or not isinstance(key, bytes) or len(key) < 32:
                raise ValueError("audit keys must have a non-empty id and at least 32 bytes")
        if self.active_key_id not in self.keys:
            raise ValueError("active audit key id is not present in keyring")

    def get(self, key_id: str | None) -> bytes | None:
        return self.keys.get(key_id) if key_id else None

    @classmethod
    def from_settings(cls, domain: str = "mongo") -> "AuditKeyring":
        prefix = domain.upper()
        configured = getattr(settings, f"{prefix}_AUDIT_HMAC_KEYS", None)
        if configured is None:
            configured = getattr(settings, "AUDIT_HMAC_KEYS", None)
        if configured is None:
            configured = {"legacy": settings.LOG_HMAC_KEY}
        active = getattr(
            settings,
            f"{prefix}_AUDIT_ACTIVE_KEY_ID",
            getattr(settings, "AUDIT_ACTIVE_KEY_ID", next(iter(configured))),
        )
        legacy = getattr(
            settings,
            f"{prefix}_AUDIT_LEGACY_KEY_ID",
            getattr(settings, "AUDIT_LEGACY_KEY_ID", "legacy" if "legacy" in configured else None),
        )
        return cls(domain=domain, active_key_id=active, keys=configured, legacy_key_id=legacy)


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    reason: str
    legacy: bool = False

    def __bool__(self) -> bool:
        return self.valid


@dataclass(frozen=True)
class ChainVerificationResult:
    valid: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    last_sequence: int = 0
    last_mac: str | None = None


def _unsigned_event(document: Mapping[str, Any]) -> dict[str, Any]:
    unsigned = deepcopy(dict(document))
    integrity = dict(unsigned.get("integrity", {}))
    integrity.pop("mac", None)
    unsigned["integrity"] = integrity
    return unsigned


def _event_mac(document: Mapping[str, Any], key: bytes) -> str:
    return sm3_hmac(key, canonical_json_bytes(_unsigned_event(document)))


def create_signed_event(
    *,
    event_type: str,
    actor: Mapping[str, Any],
    target: Mapping[str, Any],
    change: Mapping[str, Any],
    partition: str,
    sequence: int,
    previous_mac: str | None,
    keyring: AuditKeyring,
    outcome: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    event_id: UUID | str | None = None,
    occurred_at: datetime | str | None = None,
    ingested_at: datetime | str | None = None,
) -> dict[str, Any]:
    identifier = str(event_id or uuid4())
    event = {
        "_id": identifier,
        "schema_version": SCHEMA_VERSION,
        "event_id": identifier,
        "event_type": event_type,
        "occurred_at": _normalize(occurred_at or datetime.now(UTC)),
        "ingested_at": _normalize(ingested_at or datetime.now(UTC)),
        "actor": _normalize(actor),
        "target": _normalize(target),
        "context": _normalize(context or {}),
        "change": _normalize(change),
        "outcome": _normalize(outcome or {"status": "success", "error_code": None}),
        "integrity": {
            "algorithm": ALGORITHM,
            "key_id": keyring.active_key_id,
            "partition": partition,
            "sequence": sequence,
            "previous_mac": previous_mac,
            "mac": None,
        },
    }
    event["integrity"]["mac"] = _event_mac(event, keyring.keys[keyring.active_key_id])
    return event


def verify_document(document: Mapping[str, Any], keyring: AuditKeyring) -> VerificationResult:
    if "schema_version" not in document:
        if not {"action", "data", "hmac"}.issubset(document):
            return VerificationResult(False, "missing_fields", legacy=True)
        key = keyring.get(keyring.legacy_key_id)
        if key is None:
            return VerificationResult(False, "unknown_key_id", legacy=True)
        try:
            expected = sm3_hmac(key, canonical_json_bytes(document["data"], legacy=True))
        except (TypeError, ValueError):
            return VerificationResult(False, "invalid_encoding", legacy=True)
        valid = hmac.compare_digest(str(document["hmac"]), expected)
        return VerificationResult(valid, "ok" if valid else "mac_mismatch", legacy=True)

    if document.get("schema_version") != SCHEMA_VERSION:
        return VerificationResult(False, "unsupported_schema")
    if not REQUIRED_EVENT_FIELDS.issubset(document):
        return VerificationResult(False, "missing_fields")
    integrity = document.get("integrity")
    if not isinstance(integrity, Mapping) or not REQUIRED_INTEGRITY_FIELDS.issubset(integrity):
        return VerificationResult(False, "missing_fields")
    if document.get("_id") != document.get("event_id"):
        return VerificationResult(False, "id_mismatch")
    if integrity.get("algorithm") != ALGORITHM:
        return VerificationResult(False, "unsupported_algorithm")
    key = keyring.get(str(integrity.get("key_id")))
    if key is None:
        return VerificationResult(False, "unknown_key_id")
    try:
        expected = _event_mac(document, key)
    except (TypeError, ValueError):
        return VerificationResult(False, "invalid_encoding")
    supplied = integrity.get("mac")
    if not isinstance(supplied, str):
        return VerificationResult(False, "invalid_mac")
    valid = hmac.compare_digest(supplied, expected)
    return VerificationResult(valid, "ok" if valid else "mac_mismatch")


def verify_chain(
    documents: Iterable[Mapping[str, Any]],
    keyring: AuditKeyring,
    *,
    checkpoint: Mapping[str, Any] | None = None,
) -> ChainVerificationResult:
    errors: list[str] = []
    previous_mac = None
    previous_sequence = 0
    partition = None
    checkpoint_sequence = checkpoint.get("sequence") if checkpoint else None
    checkpoint_observed_mac = None

    for document in documents:
        result = verify_document(document, keyring)
        if not result.valid:
            errors.append(result.reason)
        integrity = document.get("integrity", {})
        sequence = integrity.get("sequence")
        current_partition = integrity.get("partition")
        if partition is None:
            partition = current_partition
        elif current_partition != partition:
            errors.append("partition_mismatch")
        if not isinstance(sequence, int) or sequence != previous_sequence + 1:
            errors.append(
                "sequence_gap"
                if isinstance(sequence, int) and sequence > previous_sequence
                else "sequence_mismatch"
            )
        if integrity.get("previous_mac") != previous_mac:
            errors.append("previous_mac_mismatch")
        if sequence == checkpoint_sequence:
            checkpoint_observed_mac = integrity.get("mac")
        previous_sequence = sequence if isinstance(sequence, int) else previous_sequence
        previous_mac = integrity.get("mac")

    if checkpoint:
        if checkpoint.get("partition") != partition:
            errors.append("checkpoint_partition_mismatch")
        if not isinstance(checkpoint_sequence, int) or checkpoint_sequence < 1:
            errors.append("checkpoint_sequence_invalid")
        elif checkpoint_sequence > previous_sequence:
            errors.append("tail_truncated")
        elif checkpoint_observed_mac is None:
            errors.append("checkpoint_sequence_missing")
        elif not hmac.compare_digest(str(checkpoint.get("mac", "")), str(checkpoint_observed_mac)):
            errors.append("checkpoint_mac_mismatch")

    unique_errors = tuple(dict.fromkeys(errors))
    return ChainVerificationResult(not unique_errors, unique_errors, previous_sequence, previous_mac)
