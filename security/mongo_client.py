# -*- coding: utf-8 -*-
# @File    : mongo_client.py
# @Time    : 2025/8/26 07:03
# @Author  : seveN1foR
# @Version : 2.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了Mongo客户端工厂函数
v2.0: 修复集合命名、新增 HMAC 验证、连接容错
"""

# here put the import lib
import json
import logging

from django.conf import settings
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from security.sec_utils.hmac_utils import sm3_hmac

logger = logging.getLogger(__name__)


def dict_to_bytes(data: dict) -> bytes:
    """
    把 dict 转换为确定性的 bytes
    - sort_keys=True 确保字典顺序一致
    - ensure_ascii=False 保留原始字符（比如中文）
    """
    return json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")


class MongoLogger:
    """
    MongoDB 日志客户端类
    - dev阶段可以无认证
    - 支持自动计算 HMAC
    - 支持完整性验证（verify_log / audit_all）
    - 连接容错：Mongo 不可用时降级为 no-op，不阻塞主流程
    """

    def __init__(self):
        conf = settings.MONGO
        self._connected = False
        self._collection_name = conf.get("COLLECTION", "logs")

        try:
            if conf.get("DB_USER") and conf.get("DB_PASSWORD"):
                self.client = MongoClient(
                    host=conf["HOST"],
                    port=conf["PORT"],
                    username=conf["DB_USER"],
                    password=conf["DB_PASSWORD"],
                    authSource=conf["DB_NAME"],
                    serverSelectionTimeoutMS=3000,
                    connectTimeoutMS=3000,
                )
            else:
                self.client = MongoClient(
                    host=conf["HOST"],
                    port=conf["PORT"],
                    serverSelectionTimeoutMS=3000,
                    connectTimeoutMS=3000,
                )

            # 验证连接（触发实际连接）
            self.client.admin.command("ping")
            self.db = self.client[conf["DB_NAME"]]
            self.collection = self.db[self._collection_name]  # 修复 Issue A：使用 COLLECTION 而非 DB_NAME
            self._connected = True
            logger.info(f"MongoDB 已连接: {conf['HOST']}:{conf['PORT']}/{conf['DB_NAME']}"
                        f"/{self._collection_name}")

        except PyMongoError as e:
            logger.warning(f"MongoDB 连接失败，日志暂存降级: {e}")
            self._connected = False
            self.collection = None
            self.client = None

    @property
    def connected(self) -> bool:
        """是否已成功连接 MongoDB"""
        return self._connected

    # --- 写入 ---

    def insert_log(self, action: str, data: dict):
        """
        插入一条日志，同时计算 HMAC
        :param action: 日志类型 / 操作名
        :param data: 业务数据字典
        """
        if not self._connected:
            logger.warning(f"MongoDB 不可用，跳过写入: action={action}")
            return None

        data_bytes = dict_to_bytes(data)
        hmac_val = sm3_hmac(hmac_key=settings.LOG_HMAC_KEY, msg=data_bytes)
        doc = {
            "action": action,
            "data": data,
            "hmac": hmac_val,
        }
        return self.collection.insert_one(doc)

    # --- 查询 ---

    def find_logs(self, log_filter: dict = None):
        """
        查询日志
        """
        if not self._connected:
            logger.warning("MongoDB 不可用，查询返回空列表")
            return []
        return list(self.collection.find(log_filter or {}))

    def find_all(self, limit=100):
        """返回最近 N 条日志"""
        if not self._connected:
            return []
        return list(self.collection.find().sort("_id", -1).limit(limit))

    # --- HMAC 完整性验证 (Issue B) ---

    def verify_log(self, doc: dict) -> bool:
        """
        验证单条 MongoDB 文档的 HMAC 是否匹配。
        返回 True 表示完整，False 表示被篡改。
        """
        if "hmac" not in doc or "data" not in doc:
            return False

        data_bytes = dict_to_bytes(doc["data"])
        expected = sm3_hmac(hmac_key=settings.LOG_HMAC_KEY, msg=data_bytes)
        return doc["hmac"] == expected

    def audit_all(self) -> dict:
        """
        审计 MongoDB 中所有日志的完整性。
        返回 {"total": N, "tampered": N, "healthy": N}
        """
        if not self._connected:
            return {"total": 0, "tampered": 0, "healthy": 0, "error": "MongoDB 不可用"}

        total = 0
        tampered = 0
        for doc in self.collection.find():
            total += 1
            if not self.verify_log(doc):
                tampered += 1

        return {
            "total": total,
            "tampered": tampered,
            "healthy": total - tampered,
        }

    def close(self):
        """关闭连接"""
        if self.client:
            self.client.close()
