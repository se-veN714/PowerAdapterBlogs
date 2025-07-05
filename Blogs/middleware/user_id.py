# -*- coding: utf-8 -*-
# @File    : user_id.py
# @Time    : 2025/7/6 01:01
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了网页访客信息记录功能的类和函数。
"""

# here put the import lib
import uuid

from django.utils.deprecation import MiddlewareMixin

COOKIE_KEY = 'visitor_id'
COOKIE_AGE = 60 * 60 * 24 * 365 * 10  # 10年（单位秒）


class UserIdMiddleware(MiddlewareMixin):
    def __call__(self, request):
        # 获取已有 UID，或生成新的
        uid = request.COOKIES.get(COOKIE_KEY)
        if not uid:
            uid = str(uuid.uuid4())

        request.uid = uid

        response = self.get_response(request)

        if COOKIE_KEY not in request.COOKIES:
            response.set_cookie(
                key=COOKIE_KEY,
                value=uid,
                max_age=COOKIE_AGE,
                httponly=True,
                samesite='Lax',
            )

        return response

