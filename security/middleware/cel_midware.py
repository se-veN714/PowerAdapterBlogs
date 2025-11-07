# -*- coding: utf-8 -*-
# @File    : comment_log.py
# @Time    : 2025/11/3 21:57
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了comment所属日志mongo功能的类和函数。
"""

# here put the import lib
from django.utils.deprecation import MiddlewareMixin
from security.mongo_models.cel_model import CommentEventLog


class CommentEventLogMiddleware(MiddlewareMixin):
    """
    在评论 POST 请求后，将评论相关的客户端信息写入 MongoDB
    """

    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.get_response = get_response
        self.comment_logger = CommentEventLog()  # 使用业务层封装

    def process_view(self, request, view_func, view_args, view_kwargs):
        # 仅记录评论提交请求
        if getattr(request.resolver_match, "url_name", None) == "post_comment" and request.method == "POST":
            self.comment_logger.create(
                user_id=request.user.id if request.user.is_authenticated else None,
                post_slug=view_kwargs.get("slug"),
                client_ip=getattr(request, "client_ip", None),
                ua=getattr(request, "client_ua", None),
                action="create_comment",
                extra={
                    "referrer": getattr(request, "client_referrer", None),
                    "fingerprint": getattr(request, "client_fp", None),
                }
            )

        return None  # 必须返回 None，继续请求处理
