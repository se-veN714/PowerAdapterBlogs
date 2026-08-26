"""Translate Django Admin LogEntry rows into durable audit events."""

from __future__ import annotations

import json
from functools import wraps
from uuid import UUID, uuid5

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry, LogEntryManager

from security.outbox import enqueue_audit_event


ADMIN_AUDIT_NAMESPACE = UUID("4c33906d-cd6f-4b35-bbf7-2ea0f32769b4")
ACTION_EVENT_TYPES = {
    ADDITION: "django_admin.object.added",
    CHANGE: "django_admin.object.changed",
    DELETION: "django_admin.object.deleted",
}


def _changed_fields(change_message) -> list[str]:
    if isinstance(change_message, str):
        try:
            change_message = json.loads(change_message)
        except (TypeError, ValueError):
            return []
    if not isinstance(change_message, list):
        return []
    fields = set()
    for item in change_message:
        changed = item.get("changed") if isinstance(item, dict) else None
        values = changed.get("fields") if isinstance(changed, dict) else None
        if not isinstance(values, list):
            continue
        fields.update(
            field.strip()[:64]
            for field in values
            if isinstance(field, str) and field.strip()
        )
    return sorted(fields)


def admin_event_id(log_entry: LogEntry):
    if not log_entry.pk:
        raise ValueError("saved LogEntry is required")
    return uuid5(ADMIN_AUDIT_NAMESPACE, f"django-admin-logentry:{log_entry.pk}")


def record_admin_logentry(log_entry: LogEntry):
    event_type = ACTION_EVENT_TYPES.get(log_entry.action_flag)
    if event_type is None:
        raise ValueError("unsupported Django Admin action flag")
    content_type = log_entry.content_type
    target_type = (
        f"{content_type.app_label}.{content_type.model}"
        if content_type is not None
        else "unknown"
    )
    return enqueue_audit_event(
        event_id=admin_event_id(log_entry),
        event_type=event_type,
        occurred_at=log_entry.action_time,
        actor={"type": "user", "id": str(log_entry.user_id)},
        target={
            "type": target_type,
            "id": str(log_entry.object_id or f"logentry:{log_entry.pk}"),
        },
        context={"source": "django-admin"},
        change={"fields": _changed_fields(log_entry.change_message)},
        outcome={"status": "success", "error_code": None},
    )


def install_admin_log_actions_hook():
    """Cover Django's bulk LogEntry path, which does not emit post_save."""
    current = LogEntryManager.log_actions
    if getattr(current, "_mongo_audit_hook", False):
        return

    @wraps(current)
    def audited_log_actions(manager, *args, **kwargs):
        result = current(manager, *args, **kwargs)
        entries = [result] if isinstance(result, LogEntry) else result
        for entry in entries:
            record_admin_logentry(entry)
        return result

    audited_log_actions._mongo_audit_hook = True
    LogEntryManager.log_actions = audited_log_actions
