# -*- coding: utf-8 -*-
# @File    : signals.py
# @Time    : 2025/8/3 03:00
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了security的signals功能的类和函数。
"""

from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.core.exceptions import PermissionDenied
from django.db.models.signals import post_save, pre_save, pre_delete
from django.dispatch import receiver

# here put the import lib
import logging

from accounts.thread_local import get_current_user
from security.models import SecureLogEntry

logger = logging.getLogger(__name__)

# ============================================================
# LogEntry / SecureLogEntry 不可变性保护
# 仅 superuser 可修改或删除日志记录
# ============================================================

LOG_PROTECTED_MSG = "Only superuser can modify or delete log entries"


@receiver(pre_save, sender=LogEntry)
def prevent_logentry_modify(sender, instance, **kwargs):
    """阻止非 superuser 修改已有 LogEntry。"""
    if instance.pk is None:
        return  # 新建 LogEntry 不受限制（Django 内部自动创建）
    user = get_current_user()
    if user is not None and not user.is_superuser:
        raise PermissionDenied(LOG_PROTECTED_MSG)


@receiver(pre_delete, sender=LogEntry)
def prevent_logentry_delete(sender, instance, **kwargs):
    """阻止非 superuser 删除 LogEntry。"""
    user = get_current_user()
    if user is not None and not user.is_superuser:
        raise PermissionDenied(LOG_PROTECTED_MSG)


@receiver(pre_delete, sender=SecureLogEntry)
def prevent_secure_logentry_delete(sender, instance, **kwargs):
    """阻止非 superuser 删除 SecureLogEntry（HMAC 完整性记录）。"""
    user = get_current_user()
    if user is not None and not user.is_superuser:
        raise PermissionDenied(LOG_PROTECTED_MSG)


# ============================================================
# SecureLogEntry 自动签名（创建时 HMAC）
# ============================================================

@receiver(post_save, sender=LogEntry)
def create_secure_log_entry(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        secret_key = settings.LOG_HMAC_KEY
        SecureLogEntry.compute_from_logentry(instance, secret_key)
    except Exception:
        logger.exception(f"SecureLogEntry 同步失败: logentry_id={instance.id} "
                         f"content_type_id={instance.content_type_id}")
