# -*- coding: utf-8 -*-
# @File    : audit_log_integrity.py
# @Time    : 2025/8/3 03:28
# @Author  : seveN1foR
# @Version : 2.1
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
审计日志完整性管理命令。

v2.0: 新增 --mongo 选项，支持 MongoDB 审计。
v2.1: 代码优化，统一 options 参数风格，改进边界情况处理。
"""

import logging

from django.core.management.base import BaseCommand
from django.conf import settings

from security.models import SecureLogEntry
from security.mongo_client import MongoLogger

logger = logging.getLogger(__name__)


def _format_result(label: str, total: int, tampered: int) -> str:
    """格式化审计结果为统一的可读字符串。

    Args:
        label: 数据源标签（如 "PostgreSQL"）。
        total: 日志总数。
        tampered: 被篡改的日志数。

    Returns:
        格式化后的审计结果字符串。
    """
    return (
        f"{label}: 共 {total} 条, "
        f"篡改 {tampered} 条, "
        f"健康 {total - tampered} 条"
    )


def _print_banner(stdout, title: str):
    """打印控制台分隔横幅。

    Args:
        stdout: Django stdout 句柄。
        title: 横幅标题。
    """
    stdout.write("")
    stdout.write("=" * 50)
    stdout.write(title)
    stdout.write("=" * 50)


class Command(BaseCommand):
    """审计日志完整性（PostgreSQL + 可选 MongoDB）。"""

    help = "审计日志完整性（PostgreSQL + 可选 MongoDB）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--mongo",
            action="store_true",
            default=False,
            help="同时审计 MongoDB 中的日志完整性",
        )

    def handle(self, *args, **options):
        key = settings.LOG_HMAC_KEY

        # --- PostgreSQL 审计 ---
        _print_banner(self.stdout, "PostgreSQL SecureLogEntry 审计")
        tampered = SecureLogEntry.audit_all(key)
        total = SecureLogEntry.objects.count()
        self.stdout.write(self.style.SUCCESS(_format_result("PostgreSQL", total, tampered)))

        if tampered > 0:
            logger.warning("日志完整性审计: PostgreSQL 发现篡改 %d/%d 条", tampered, total)

        # --- MongoDB 审计（可选）---
        if not options.get("mongo"):
            return

        _print_banner(self.stdout, "MongoDB 日志审计")

        mongo = MongoLogger()
        try:
            if not mongo.connected:
                self.stdout.write(self.style.WARNING("MongoDB 不可用，跳过审计"))
                return

            result = mongo.audit_all()
            self.stdout.write(
                self.style.SUCCESS(
                    _format_result("MongoDB", result["total"], result["tampered"])
                )
            )
            if result["tampered"] > 0:
                logger.warning(
                    "日志完整性审计: MongoDB 发现篡改 %d/%d 条",
                    result["tampered"], result["total"],
                )
        finally:
            mongo.close()