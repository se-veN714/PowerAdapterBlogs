# -*- coding: utf-8 -*-
# @File    : services.py
# @Time    : 2025/9/2 05:53
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了security视图/服务层功能的类和函数。
"""

# here put the import lib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from comment.models import Comment
from security.models import SecureLogEntry
from security.outbox import enqueue_audit_event

logger = logging.getLogger(__name__)

COMMENT_REASON_CODES = {
    "spam": "SPAM",
    "offensive": "OFFENSIVE",
    "abuse": "ABUSE",
    "legal": "LEGAL",
    "duplicate": "DUPLICATE",
    "requested": "REQUESTED",
}


def _comment_reason_code(reason):
    return COMMENT_REASON_CODES.get(str(reason or "").strip().lower(), "OTHER")


@dataclass(frozen=True, slots=True)
class IntegrityAuditResult:
    checked: int
    tampered: int


@transaction.atomic
def audit_secure_log_entries(*, actor, entry_ids) -> IntegrityAuditResult:
    """Audit at most one UI page of immutable integrity records atomically."""
    if not getattr(actor, "is_active", False) or not (
        actor.is_superuser or actor.has_perm("security.run_integrity_audit")
    ):
        raise PermissionDenied("当前账号没有运行完整性审计的权限。")

    try:
        normalized_ids = {
            int(entry_id)
            for entry_id in entry_ids
            if str(entry_id).strip()
        }
    except (TypeError, ValueError) as exc:
        raise ValidationError("审计记录编号无效。") from exc
    if not normalized_ids:
        raise ValidationError("请至少选择一条需要核验的记录。")
    if len(normalized_ids) > 100:
        raise ValidationError("单次最多核验 100 条记录。")

    entries = list(
        SecureLogEntry.objects.select_for_update()
        .filter(pk__in=normalized_ids)
        .select_related("log_entry")
        .order_by("pk")
    )
    if len(entries) != len(normalized_ids):
        raise ValidationError("部分审计记录已不存在，请刷新页面后重试。")

    tampered = sum(
        SecureLogEntry.audit(entry, settings.LOG_HMAC_KEY)
        for entry in entries
    )
    LogEntry.objects.create(
        user=actor,
        content_type=ContentType.objects.get_for_model(SecureLogEntry),
        object_id="",
        object_repr=f"Integrity audit batch ({len(entries)} records)",
        action_flag=CHANGE,
        change_message=(
            f"operations_security checked={len(entries)} tampered={tampered}"
        ),
    )
    return IntegrityAuditResult(checked=len(entries), tampered=tampered)


def moderate_comment(*, comment: Comment, new_status: int, request, reason: str | None = None):
    """Update one comment and enqueue minimized audit evidence atomically."""
    allowed_statuses = {int(value) for value, _label in Comment.Status.choices}
    normalized_status = int(new_status)
    if normalized_status not in allowed_statuses:
        raise ValueError("unsupported comment moderation status")

    actor = getattr(request, "user", None)
    actor_id = (
        str(actor.pk)
        if actor is not None and getattr(actor, "is_authenticated", False)
        else "system"
    )
    with transaction.atomic():
        locked = Comment.objects.select_for_update().get(pk=comment.pk)
        old_status = int(locked.status)
        locked.status = normalized_status
        locked.save(update_fields=["status"])
        enqueue_audit_event(
            event_type="comment.moderated",
            actor={
                "type": "user" if actor_id != "system" else "system",
                "id": actor_id,
            },
            target={"type": "comment", "id": str(locked.pk)},
            context={"source": "web"},
            change={
                "before": {"status": old_status},
                "after": {"status": normalized_status},
                "reason_code": _comment_reason_code(reason),
            },
            outcome={"status": "success", "error_code": None},
        )
    comment.status = normalized_status
    return comment
