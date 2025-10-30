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
from .models import Comment, CommentEventLog


def moderate_comment(*, comment: Comment, new_status: str, request, reason: str | None = None):
    """
    Moderates a comment and logs the moderation event.

    This function updates the status of a comment (e.g., from pending to approved)
    and records the action in CommentEventLog for auditing and traceability.

    Args:
        comment (Comment): The comment instance being moderated.
        new_status (str): The new moderation status to apply to the comment.
        request (HttpRequest): The request object from which client metadata (IP, UA, etc.) is extracted.
        reason (str | None, optional): Optional reason for moderation (e.g., "spam", "offensive", etc.).
            Defaults to None.

    Side Effects:
        - Updates the `status` and `created_time` fields of the Comment object.
        - Creates a new CommentEventLog entry with contextual client information.

    """
    old = comment.status
    comment.status = new_status
    comment.save(update_fields=["status", "created_time"])

    snapshot = {
        "id": comment.id,
        "old_status": old,
        "new_status": comment.status,
        "reason": reason,
    }

    CommentEventLog.objects.create(
        comment=comment,
        action=CommentEventLog.UserAction.MODERATE,
        ip_address=getattr(request, "client_ip", None),
        user_agent=getattr(request, "client_ua", ""),
        referrer=getattr(request, "client_referrer", ""),
        url_path=getattr(request, "client_path", ""),
        client_fingerprint=getattr(request, "client_fp", ""),
        comment_snapshot=snapshot,
    )
