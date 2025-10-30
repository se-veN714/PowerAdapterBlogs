# -*- coding: utf-8 -*-
# @File    : mongo_client.py
# @Time    : 2025/8/26 07:03
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了Mongo客户端工厂函数
"""

# here put the import lib
import json

from django.conf import settings
from pymongo import MongoClient

from security.sec_utils.hmac_utils import sm3_hmac


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
    """

    def __init__(self):
        conf = settings.MONGO
        if conf.get("DB_USER") and conf.get("DB_PASSWORD"):
            self.client = MongoClient(
                host=conf["HOST"],
                port=conf["PORT"],
                username=conf["DB_USER"],
                password=conf["DB_PASSWORD"],
                authSource=conf["DB_NAME"],  # 默认认证到目标库
            )
        else:
            self.client = MongoClient(
                host=conf["HOST"],
                port=conf["PORT"],
            )

        self.db = self.client[conf["DB_NAME"]]
        self.collection = self.db[conf["DB_NAME"]]

    def insert_log(self, action: str, data: dict):
        """
        插入一条日志，同时计算 HMAC
        :param action: 日志类型 / 操作名
        :param data: 业务数据字典
        """
        data_bytes = json.dumps(data,sort_keys=True, ensure_ascii=False).encode("utf-8")
        hmac_val = sm3_hmac(hmac_key=settings.LOG_HMAC_KEY, msg=data_bytes)
        doc = {
            "action": action,
            "data": data,
            "hmac": hmac_val
        }
        return self.collection.insert_one(doc)

    def find_logs(self, log_filter: dict = None):
        """
        查询日志
        """
        return list(self.collection.find(log_filter or {}))
