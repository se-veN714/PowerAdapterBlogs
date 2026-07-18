# -*- coding: utf-8 -*-
# @File    : init_log_hmac.py
# @Time    : 2025/8/3 02:47
# @Author  : seveN1foR
# @Version : 2.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""初始化或安全升级 PostgreSQL ``LogEntry`` HMAC。"""

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
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            '--repair-known',
            action='store_true',
            default=False,
            help='仅升级能够由已知旧算法验证的 HMAC',
        )
        mode.add_argument(
            '--force',
            action='store_true',
            default=False,
            help='覆盖全部已有 HMAC；会重建信任基线，仅限完成取证后使用',
        )

    def handle(self, *args, **options):
        secret_key = settings.LOG_HMAC_KEY
        created_count = 0
        updated_count = 0
        skipped_count = 0
        unknown_count = 0
        force = options.get("force")
        repair_known = options.get("repair_known")
        mode = "force" if force else "repair-known" if repair_known else "init"

        logger.info("init_log_hmac 开始: mode=%s", mode)

        entries = LogEntry.objects.select_related("securelogentry").all()
        for entry in entries:
            try:
                secure_entry = entry.securelogentry
            except SecureLogEntry.DoesNotExist:
                SecureLogEntry.compute_from_logentry(entry, secret_key)
                created_count += 1
                continue

            if force:
                SecureLogEntry.resign(secure_entry, secret_key)
                updated_count += 1
                continue

            if repair_known:
                if SecureLogEntry.has_valid_hmac(secure_entry, secret_key):
                    skipped_count += 1
                    continue
                legacy_format = SecureLogEntry.identify_known_legacy_format(
                    secure_entry,
                    secret_key,
                )
                if legacy_format is None:
                    unknown_count += 1
                    continue
                SecureLogEntry.resign(secure_entry, secret_key)
                updated_count += 1
                continue

            skipped_count += 1

        logger.info(
            "init_log_hmac 完成: mode=%s created=%d updated=%d skipped=%d unknown=%d",
            mode,
            created_count,
            updated_count,
            skipped_count,
            unknown_count,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"完成: 新创建 {created_count} 条, 更新 {updated_count} 条, "
                f"跳过 {skipped_count} 条, 未知/可疑 {unknown_count} 条。"
            )
        )
