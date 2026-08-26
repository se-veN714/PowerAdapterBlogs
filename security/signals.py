"""Append-only guards and durable Django Admin audit capture."""

from django.contrib.admin.models import LogEntry
from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from security.admin_audit import record_admin_logentry
from security.models import (
    AuditCheckpoint,
    AuditOutbox,
    AuditVerificationRun,
    SecureLogEntry,
)


LOG_ENTRY_IMMUTABLE_FIELDS = (
    "action_time",
    "user_id",
    "content_type_id",
    "object_id",
    "object_repr",
    "action_flag",
    "change_message",
)
INTEGRITY_IMMUTABLE_FIELDS = ("log_entry_id", "hmac")
OUTBOX_IMMUTABLE_FIELDS = ("event_id", "event_type", "partition", "event")
CHECKPOINT_IMMUTABLE_FIELDS = (
    "partition",
    "sequence",
    "mac",
    "key_id",
    "checkpoint_hmac",
)
VERIFICATION_RUN_IMMUTABLE_FIELDS = ("scope", "partition")


@receiver(post_save, sender=LogEntry)
def enqueue_admin_audit_event(sender, instance, created, **kwargs):
    if created:
        record_admin_logentry(instance)


@receiver(pre_save, sender=LogEntry)
def prevent_log_entry_rewrite(sender, instance, **kwargs):
    if not instance.pk:
        return
    original = sender.objects.filter(pk=instance.pk).values(*LOG_ENTRY_IMMUTABLE_FIELDS).first()
    if original and any(
        getattr(instance, field) != original[field]
        for field in LOG_ENTRY_IMMUTABLE_FIELDS
    ):
        raise ProtectedError("audit LogEntry records are append-only", [instance])


@receiver(pre_save, sender=SecureLogEntry)
def prevent_integrity_rewrite(sender, instance, **kwargs):
    if not instance.pk:
        return
    original = sender.objects.filter(pk=instance.pk).values(*INTEGRITY_IMMUTABLE_FIELDS).first()
    if original and any(
        getattr(instance, field) != original[field]
        for field in INTEGRITY_IMMUTABLE_FIELDS
    ):
        raise ProtectedError("audit integrity evidence is append-only", [instance])


def _prevent_field_rewrite(sender, instance, fields, message):
    if not instance.pk:
        return
    original = sender.objects.filter(pk=instance.pk).values(*fields).first()
    if original and any(getattr(instance, field) != original[field] for field in fields):
        raise ProtectedError(message, [instance])


@receiver(pre_save, sender=AuditOutbox)
def prevent_outbox_payload_rewrite(sender, instance, **kwargs):
    _prevent_field_rewrite(
        sender,
        instance,
        OUTBOX_IMMUTABLE_FIELDS,
        "audit outbox payloads are immutable",
    )


@receiver(pre_save, sender=AuditCheckpoint)
def prevent_checkpoint_rewrite(sender, instance, **kwargs):
    _prevent_field_rewrite(
        sender,
        instance,
        CHECKPOINT_IMMUTABLE_FIELDS,
        "audit checkpoints are immutable",
    )


@receiver(pre_save, sender=AuditVerificationRun)
def prevent_verification_scope_rewrite(sender, instance, **kwargs):
    _prevent_field_rewrite(
        sender,
        instance,
        VERIFICATION_RUN_IMMUTABLE_FIELDS,
        "audit verification scope is immutable",
    )


@receiver(pre_delete, sender=LogEntry)
@receiver(pre_delete, sender=SecureLogEntry)
@receiver(pre_delete, sender=AuditOutbox)
@receiver(pre_delete, sender=AuditCheckpoint)
@receiver(pre_delete, sender=AuditVerificationRun)
def prevent_audit_evidence_deletion(sender, instance, **kwargs):
    raise ProtectedError("audit evidence deletion is disabled", [instance])
