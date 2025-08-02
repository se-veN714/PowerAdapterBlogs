# -*- coding: utf-8 -*-
# @File    : init_log_hmac.py
# @Time    : 2025/8/3 02:47
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了XXX功能的类和函数。
"""

# here put the import lib
from django.core.management.base import BaseCommand
from django.contrib.admin.models import LogEntry
from django.conf import settings

from security.models import SecureLogEntry

class Command(BaseCommand):
    help = '初始化所有日志的 HMAC 完整性记录'

    def handle(self, *args, **options):
        secret_key = settings.LOG_HMAC_KEY
        count = 0

        for entry in LogEntry.objects.all():
            _, created = SecureLogEntry.compute_from_logentry(entry, secret_key)

            if created:
                count += 1

        self.stdout.write(self.style.SUCCESS(f"成功初始化 {count} 条日志完整性记录。"))
