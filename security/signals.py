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

# here put the import lib
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.db.models.signals import post_save
from django.dispatch import receiver

from security.models import SecureLogEntry


@receiver(post_save, sender=LogEntry)
def create_secure_log_entry(sender, instance, created, **kwargs):
    if not created:
        return

    secret_key = settings.LOG_HMAC_KEY
    SecureLogEntry.compute_from_logentry(instance, secret_key)
