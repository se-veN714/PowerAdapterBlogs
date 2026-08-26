"""Transactional audit outbox, lease-safe delivery, and reconciliation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Min, Q
from django.utils import timezone

from security.audit import IMMUTABLE_EVENT_FIELDS, canonical_json_bytes, verify_document
from security.models import AuditOutbox


logger = logging.getLogger(__name__)


class AuditEventCollision(ValueError):
    pass


class InvalidAuditReceipt(RuntimeError):
    pass


@dataclass(frozen=True)
class DeliveryBatchResult:
    delivered: int = 0
    failed: int = 0
    dead: int = 0
    lost_leases: int = 0


@dataclass(frozen=True)
class ReconciliationResult:
    checked: int = 0
    missing: int = 0
    invalid: int = 0
    receipt_mismatch: int = 0

    @property
    def healthy(self) -> bool:
        return not (self.missing or self.invalid or self.receipt_mismatch)


@dataclass(frozen=True)
class OutboxHealth:
    healthy: bool
    pending: int
    due_pending: int
    processing: int
    stale_processing: int
    dead: int
    oldest_pending_seconds: int
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "pending": self.pending,
            "due_pending": self.due_pending,
            "processing": self.processing,
            "stale_processing": self.stale_processing,
            "dead": self.dead,
            "oldest_pending_seconds": self.oldest_pending_seconds,
            "reason_codes": list(self.reason_codes),
        }


def collect_outbox_health(
    *,
    max_pending: int = 1000,
    max_oldest_pending_seconds: int = 300,
    lease_seconds: int = 300,
) -> OutboxHealth:
    now = timezone.now()
    stale_before = now - timedelta(seconds=max(30, lease_seconds))
    pending_rows = AuditOutbox.objects.filter(status=AuditOutbox.Status.PENDING)
    processing_rows = AuditOutbox.objects.filter(status=AuditOutbox.Status.PROCESSING)
    oldest_created_at = pending_rows.aggregate(value=Min("created_at"))["value"]
    oldest_seconds = max(0, int((now - oldest_created_at).total_seconds())) if oldest_created_at else 0
    pending = pending_rows.count()
    processing = processing_rows.count()
    stale = processing_rows.filter(
        Q(locked_at__isnull=True) | Q(locked_at__lte=stale_before)
    ).count()
    dead = AuditOutbox.objects.filter(status=AuditOutbox.Status.DEAD).count()
    due = pending_rows.filter(next_attempt_at__lte=now).count()
    reasons = []
    if dead:
        reasons.append("dead_letters")
    if stale:
        reasons.append("stale_processing")
    if pending > max(0, max_pending):
        reasons.append("pending_count_exceeded")
    if oldest_seconds > max(0, max_oldest_pending_seconds):
        reasons.append("oldest_pending_exceeded")
    return OutboxHealth(
        healthy=not reasons,
        pending=pending,
        due_pending=due,
        processing=processing,
        stale_processing=stale,
        dead=dead,
        oldest_pending_seconds=oldest_seconds,
        reason_codes=tuple(reasons),
    )


def _canonical_value(value):
    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def _partition_for(event_type: str, occurred_at: datetime) -> str:
    domain = event_type.split(".", 1)[0].lower()
    return f"{domain}:{occurred_at.astimezone(UTC):%Y-%m}"


def enqueue_audit_event(
    *,
    event_type: str,
    actor: Mapping[str, Any],
    target: Mapping[str, Any],
    change: Mapping[str, Any],
    outcome: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    event_id: UUID | str | None = None,
    occurred_at: datetime | None = None,
    partition: str | None = None,
) -> AuditOutbox:
    """Insert a canonical event in the caller's relational transaction."""
    identifier = UUID(str(event_id)) if event_id else uuid4()
    existing = AuditOutbox.objects.filter(event_id=identifier).first()

    effective_occurred_at = occurred_at or timezone.now()
    if existing is not None and occurred_at is None:
        canonical_occurred_at = existing.event.get("occurred_at")
    else:
        canonical_occurred_at = _canonical_value(effective_occurred_at)
    canonical_partition = partition or (
        existing.partition
        if existing is not None and occurred_at is None
        else _partition_for(event_type, effective_occurred_at)
    )
    event = {
        "schema_version": 1,
        "event_id": str(identifier),
        "event_type": event_type,
        "occurred_at": canonical_occurred_at,
        "actor": _canonical_value(actor),
        "target": _canonical_value(target),
        "context": _canonical_value(context or {"source": "application"}),
        "change": _canonical_value(change),
        "outcome": _canonical_value(outcome or {"status": "success", "error_code": None}),
    }
    if existing is not None:
        if existing.partition == canonical_partition and existing.event == event:
            return existing
        raise AuditEventCollision("event_id is already bound to different canonical content")

    row, created = AuditOutbox.objects.get_or_create(
        event_id=identifier,
        defaults={
            "event_type": event_type,
            "partition": canonical_partition,
            "event": event,
        },
    )
    if not created and (row.partition != canonical_partition or row.event != event):
        raise AuditEventCollision("event_id is already bound to different canonical content")
    return row


def _claim_one(now, *, lease_seconds: int):
    stale_before = now - timedelta(seconds=max(30, lease_seconds))
    token = uuid4()
    with transaction.atomic():
        row = (
            AuditOutbox.objects.select_for_update()
            .filter(
                Q(status=AuditOutbox.Status.PENDING, next_attempt_at__lte=now)
                | Q(status=AuditOutbox.Status.PROCESSING, locked_at__lte=stale_before)
                | Q(status=AuditOutbox.Status.PROCESSING, locked_at__isnull=True)
            )
            .order_by("created_at", "pk")
            .first()
        )
        if row is None:
            return None
        row.status = AuditOutbox.Status.PROCESSING
        row.locked_at = now
        row.lock_token = token
        row.save(update_fields=["status", "locked_at", "lock_token"])
        return row, token


def _validated_receipt(receipt, *, expected_partition: str):
    if not isinstance(receipt, Mapping):
        raise InvalidAuditReceipt("missing_receipt")
    integrity = receipt.get("integrity")
    if not isinstance(integrity, Mapping):
        raise InvalidAuditReceipt("missing_integrity")
    sequence = integrity.get("sequence")
    mac = integrity.get("mac")
    if not isinstance(sequence, int) or sequence < 1:
        raise InvalidAuditReceipt("invalid_sequence")
    if not isinstance(mac, str) or not mac:
        raise InvalidAuditReceipt("invalid_mac")
    if integrity.get("partition") != expected_partition:
        raise InvalidAuditReceipt("partition_mismatch")
    return sequence, mac


def deliver_outbox_batch(
    *,
    writer=None,
    limit: int = 100,
    max_attempts: int = 12,
    lease_seconds: int = 300,
) -> DeliveryBatchResult:
    """Deliver a bounded batch; stale workers cannot overwrite a newer lease."""
    if writer is None:
        from security.mongo_client import MongoLogger

        writer = MongoLogger()
    delivered = failed = dead = lost_leases = 0
    for _ in range(max(0, min(limit, 1000))):
        claim = _claim_one(timezone.now(), lease_seconds=lease_seconds)
        if claim is None:
            break
        row, token = claim
        try:
            receipt = writer.insert_event(row.event, partition=row.partition)
            sequence, mac = _validated_receipt(receipt, expected_partition=row.partition)
        except Exception as exc:
            attempts = row.attempts + 1
            terminal = attempts >= max(1, max_attempts)
            updated = AuditOutbox.objects.filter(
                pk=row.pk,
                status=AuditOutbox.Status.PROCESSING,
                lock_token=token,
            ).update(
                status=AuditOutbox.Status.DEAD if terminal else AuditOutbox.Status.PENDING,
                attempts=attempts,
                last_error_code=type(exc).__name__[:64],
                lock_token=None,
                locked_at=None,
                next_attempt_at=timezone.now()
                + timedelta(seconds=min(3600, 2 ** min(attempts, 12))),
            )
            if not updated:
                lost_leases += 1
                continue
            logger.warning(
                "audit delivery failed event_id=%s error_code=%s attempts=%s",
                row.event_id,
                type(exc).__name__[:64],
                attempts,
            )
            failed += 1
            dead += int(terminal)
            continue

        updated = AuditOutbox.objects.filter(
            pk=row.pk,
            status=AuditOutbox.Status.PROCESSING,
            lock_token=token,
        ).update(
            status=AuditOutbox.Status.DELIVERED,
            attempts=row.attempts + 1,
            last_error_code="",
            lock_token=None,
            locked_at=None,
            delivered_at=timezone.now(),
            delivery_sequence=sequence,
            delivery_mac=mac,
        )
        if updated:
            delivered += 1
        else:
            lost_leases += 1
    return DeliveryBatchResult(delivered, failed, dead, lost_leases)


def reconcile_delivered_outbox(*, writer=None, limit: int = 200) -> ReconciliationResult:
    """Compare bounded delivered receipts with Mongo-authoritative evidence."""
    if writer is None:
        from security.mongo_client import MongoLogger

        writer = MongoLogger()
    rows = AuditOutbox.objects.filter(status=AuditOutbox.Status.DELIVERED).order_by("pk")[
        : max(1, min(int(limit), 1000))
    ]
    checked = missing = invalid = receipt_mismatch = 0
    for row in rows:
        checked += 1
        document = writer.collection.find_one({"_id": str(row.event_id)})
        if document is None:
            missing += 1
            continue
        verification = verify_document(document, writer.keyring)
        if not verification.valid:
            invalid += 1
            continue
        integrity = document.get("integrity", {})
        canonical_matches = all(
            document.get(field) == row.event.get(field)
            for field in IMMUTABLE_EVENT_FIELDS
        )
        receipt_matches = (
            integrity.get("partition") == row.partition
            and integrity.get("sequence") == row.delivery_sequence
            and integrity.get("mac") == row.delivery_mac
        )
        if not canonical_matches or not receipt_matches:
            receipt_mismatch += 1
    return ReconciliationResult(checked, missing, invalid, receipt_mismatch)
