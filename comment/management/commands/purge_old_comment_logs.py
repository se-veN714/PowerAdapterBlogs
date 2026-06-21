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
import logging
from datetime import datetime, timedelta, timezone

from bson.objectid import ObjectId
from django.conf import settings
from django.core.management.base import BaseCommand
from pymongo import MongoClient
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


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

        logger.info(f"purge_old_comment_logs 开始: cutoff_date={cutoff.isoformat()} days={days}")

        try:
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
            collection = db[conf.get("COLLECTION", "logs")]  # 修复 Issue A：使用 COLLECTION 而非 DB_NAME

            # --- 清理策略 ---
            # 默认 ObjectId 的生成时间反映文档创建时间
            # 所以我们用 ObjectId 的时间戳做条件过滤
            cutoff_oid = ObjectId.from_datetime(cutoff)
            result = collection.delete_many({"_id": {"$lt": cutoff_oid}})

            logger.info(f"purge_old_comment_logs 完成: deleted_count={result.deleted_count}")

            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {result.deleted_count} old comment logs older than {days} days."
                )
            )

            client.close()

        except PyMongoError as e:
            logger.exception(f"MongoDB 日志清理失败: error={e}")
            self.stdout.write(self.style.ERROR(f"MongoDB 清理失败: {e}"))
