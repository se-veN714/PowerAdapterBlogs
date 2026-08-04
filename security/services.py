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
from security.mongo_client import MongoLogger
from security.models import SecureLogEntry

logger = logging.getLogger(__name__)


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
    """
    Moderates a comment and logs the moderation event.

    This function updates the status of a comment (e.g., from pending to approved)
    and records the action in MongoDB for auditing and traceability.

    Args:
        comment (Comment): The comment instance being moderated.
        new_status (str): The new moderation status to apply to the comment.
        request (HttpRequest): The request object from which client metadata (IP, UA, etc.) is extracted.
        reason (str | None, optional): Optional reason for moderation (e.g., "spam", "offensive", etc.).
            Defaults to None.

    Side Effects:
        - Updates the `status` and `created_time` fields of the Comment object.
        - Writes an audit log to MongoDB (gracefully degrades if MongoDB is unavailable).

    """
    # 保存原状态
    old_status = comment.status
    comment.status = int(new_status)
    comment.save(update_fields=["status"])

    # 构造快照（留痕）
    snapshot = {
        "id": comment.id,
        "old_status": old_status,
        "new_status": comment.status,
        "reason": reason,
    }

    # 准备日志数据
    log_data = {
        "comment_id": comment.id,
        "action": "MODERATE",
        "snapshot": snapshot,
        "client": {
            "ip": getattr(request, "client_ip", None),
            "ua": getattr(request, "client_ua", ""),
            "referrer": getattr(request, "client_referrer", ""),
            "url": getattr(request, "client_path", ""),
            "fp": getattr(request, "client_fp", ""),
        },
        "user": str(getattr(request, "user", None)),  # 避免 Django User 对象无法 JSON 化
    }

    # 写入 MongoDB 日志（连接容错）
    try:
        mongo_logger = MongoLogger()
        mongo_logger.insert_log(action="moderate_comment", data=log_data)
    except Exception as e:
        logger.warning(
            "MongoDB 审核日志写入失败（评论状态已更新）: "
            "comment_id=%s old_status=%s new_status=%s error=%s",
            comment.id,
            old_status,
            comment.status,
            e,
        )
