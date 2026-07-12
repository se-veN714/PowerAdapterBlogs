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

from comment.models import Comment
from security.mongo_client import MongoLogger

logger = logging.getLogger(__name__)


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
