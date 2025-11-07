# -*- coding: utf-8 -*-
# @File    : comment_log.py
# @Time    : 2025/11/8 02:23
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供 CommentEventLog 的 MongoDB 实现功能的类和函数。

"""

# here put the import lib

from datetime import datetime, timezone

from security.mongo_client import MongoLogger


class CommentEventLog:
    """
    评论事件日志（MongoDB版）
    """

    def __init__(self):
        self.mongo = MongoLogger()
        self.collection = self.mongo.collection  # 可直接使用

    # --- C ---
    def create(self, user_id, post_slug, client_ip, ua, action, extra=None):
        """
        插入一条评论事件日志
        """
        data = {
            "user_id": user_id,
            "post_slug": post_slug,
            "client_ip": client_ip,
            "user_agent": ua,
            "action": action,
            "extra": extra or {},
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        return self.mongo.insert_log(action="comment_event", data=data)

    # --- R ---
    def get_all(self, limit=50):
        """返回最新的日志"""
        return list(self.collection.find().sort("created_at", -1).limit(limit))

    def find_by_user(self, user_id):
        """按用户查询"""
        return list(self.collection.find({"data.user_id": user_id}))

    def find_by_post(self, post_slug):
        """按文章 slug 查询"""
        return list(self.collection.find({"data.post_slug": post_slug}))

    # --- U ---
    def update_log(self, log_id, update_fields: dict):
        """更新指定日志"""
        return self.collection.update_one(
            {"_id": log_id},
            {"$set": update_fields}
        )

    # --- D ---
    def delete_log(self, log_id):
        """删除指定日志"""
        return self.collection.delete_one({"_id": log_id})
