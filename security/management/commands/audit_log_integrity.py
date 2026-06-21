# -*- coding: utf-8 -*-
# @File    : audit_log_integrity.py
# @Time    : 2025/8/3 03:28
# @Author  : seveN1foR
# @Version : 2.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了审计日志完整性指令功能的类和函数。
v2.0: 新增 --mongo 选项，支持 MongoDB 审计
"""

# here put the import lib
import logging

from django.core.management.base import BaseCommand
from django.conf import settings
from security.models import SecureLogEntry
from security.mongo_client import MongoLogger

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "审计日志完整性（PostgreSQL + 可选 MongoDB）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--mongo",
            action="store_true",
            default=False,
            help="同时审计 MongoDB 中的日志完整性"
        )

    def handle(self, *args, **kwargs):
        key = settings.LOG_HMAC_KEY

        # --- PostgreSQL 审计 ---
        self.stdout.write("=" * 50)
        self.stdout.write("PostgreSQL SecureLogEntry 审计")
        self.stdout.write("=" * 50)
        tampered = SecureLogEntry.audit_all(key)
        total = SecureLogEntry.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"审计完成: 共 {total} 条, 篡改 {tampered} 条, 健康 {total - tampered} 条"
            )
        )
        if tampered > 0:
            logger.warning(f"日志完整性审计: 发现篡改 {tampered}/{total} 条")

        # --- MongoDB 审计（可选）---
        if kwargs.get("mongo"):
            self.stdout.write("")
            self.stdout.write("=" * 50)
            self.stdout.write("MongoDB 日志审计")
            self.stdout.write("=" * 50)

            mongo = MongoLogger()
            if not mongo.connected:
                self.stdout.write(self.style.WARNING("MongoDB 不可用，跳过审计"))
            else:
                result = mongo.audit_all()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"审计完成: 共 {result['total']} 条, "
                        f"篡改 {result['tampered']} 条, "
                        f"健康 {result['healthy']} 条"
                    )
                )
                mongo.close()