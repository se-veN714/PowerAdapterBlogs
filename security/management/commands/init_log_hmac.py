# -*- coding: utf-8 -*-
# @File    : init_log_hmac.py
# @Time    : 2025/8/3 02:47
# @Author  : seveN1foR
# @Version : 2.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了 HMAC 初始化/重建指令功能的类和函数。
v2.0: 新增 --force 选项，支持重新计算所有已存在的 HMAC（用于 message 格式变更后）
"""

# here put the import lib
import logging

from django.core.management.base import BaseCommand
from django.contrib.admin.models import LogEntry
from django.conf import settings

from security.models import SecureLogEntry

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '初始化所有日志的 HMAC 完整性记录'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            default=False,
            help='强制重新计算所有已存在的 HMAC（用于 compose_message 格式变更后）',
        )

    def handle(self, *args, **options):
        secret_key = settings.LOG_HMAC_KEY
        created_count = 0
        updated_count = 0
        force = options.get("force")

        logger.info(f"init_log_hmac 开始: mode={'force' if force else 'init'}")

        for entry in LogEntry.objects.all():
            _, created = SecureLogEntry.compute_from_logentry(entry, secret_key)
            if created:
                created_count += 1
            elif force:
                # 强制重新计算
                SecureLogEntry.compute_from_logentry(entry, secret_key)
                updated_count += 1

        logger.info(f"init_log_hmac 完成: created={created_count} updated={updated_count}")

        self.stdout.write(
            self.style.SUCCESS(
                f"完成: 新创建 {created_count} 条"
                + (f", 重新计算 {updated_count} 条" if updated_count else "")
                + " 日志完整性记录。"
            )
        )
