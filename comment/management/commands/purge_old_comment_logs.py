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
from datetime import datetime, timedelta, timezone

from bson.objectid import ObjectId
from django.conf import settings
from django.core.management.base import BaseCommand
from pymongo import MongoClient


class Command(BaseCommand):
    help = "按照合规策略清理超过保留期的评论事件日志（MongoDB 版）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=200,
            help="保留天数（不少于180）；默认200天给缓冲"
        )

    def handle(self, *args, **options):
        # --- 参数和时间边界 ---
        days = max(180, options["days"])
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # --- 建立 MongoDB 连接 ---
        conf = settings.MONGO
        client = MongoClient(
            host=conf["HOST"],
            port=conf["PORT"],
            username=conf.get("DB_USER"),
            password=conf.get("DB_PASSWORD"),
            authSource=conf.get("DB_NAME"),
        )
        db = client[conf["DB_NAME"]]
        collection = db[conf["DB_NAME"]]  # 与你 MongoLogger 的写法一致

        # --- 清理策略 ---
        # 默认 ObjectId 的生成时间反映文档创建时间
        # 所以我们用 ObjectId 的时间戳做条件过滤
        cutoff_oid = ObjectId.from_datetime(cutoff)
        result = collection.delete_many({"_id": {"$lt": cutoff_oid}})

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {result.deleted_count} old comment logs older than {days} days."
            )
        )

        client.close()
