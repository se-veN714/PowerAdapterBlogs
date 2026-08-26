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

class CommentEventLog:
    """
    Retired compatibility shell.

    Formal security audit writes use the transactional outbox and formal reads
    use ``security.queries`` so every returned event receives verification.
    """

    def __init__(self):
        raise RuntimeError(
            "CommentEventLog is retired; use the audit outbox/query services"
        )

    # --- C ---
    def create(self, user_id, post_slug, client_ip, ua, action, extra=None):
        raise RuntimeError(
            "CommentEventLog direct writes are retired; use a transactional audit service"
        )

    # --- R ---
    def get_all(self, limit=50):
        raise RuntimeError("direct audit reads are disabled")

    def find_by_user(self, user_id):
        raise RuntimeError("direct audit reads are disabled")

    def find_by_post(self, post_slug):
        raise RuntimeError("direct audit reads are disabled")

    # --- U ---
    def update_log(self, log_id, update_fields: dict):
        raise RuntimeError(
            "security audit evidence is append-only and cannot be updated"
        )

    # --- D ---
    def delete_log(self, log_id):
        raise RuntimeError(
            "security audit evidence is append-only and cannot be deleted"
        )
