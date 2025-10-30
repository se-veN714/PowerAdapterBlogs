# -*- coding: utf-8 -*-
# @File    : purge_old_comment_logs.py
# @Time    : 2025/9/2 05:58
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了comment终端命令功能的类和函数。
"""

# here put the import lib
from datetime import timedelta

from security.models import CommentEventLog
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "按照合规策略清理超过保留期的评论事件日志"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=200, help="保留天数（不少于180）；默认200天给缓冲")

    def handle(self, *args, **options):
        days = max(180, options["days"])  # 合规下限保护
        cutoff = timezone.now() - timedelta(days=days)
        qs = CommentEventLog.objects.filter(action_at__lt=cutoff)
        count = qs.count()
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} old logs (older than {days} days)."))
