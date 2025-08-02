# -*- coding: utf-8 -*-
# @File    : audit_log_integrity.py
# @Time    : 2025/8/3 03:28
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了审计日志指令功能的类和函数。
"""

# here put the import lib
from django.core.management.base import BaseCommand
from django.conf import settings
from security.models import SecureLogEntry

class Command(BaseCommand):
    help = "审计日志完整性"

    def handle(self, *args, **kwargs):
        key = settings.LOG_HMAC_KEY
        tampered = SecureLogEntry.audit_all(key)
        self.stdout.write(self.style.SUCCESS(f"审计完成，发现篡改日志 {tampered} 条"))