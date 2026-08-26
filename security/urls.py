# -*- coding: utf-8 -*-
# @File    : urls.py
# @Time    : 2025/10/30 20:59
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了security路由功能的类和函数。
"""

# here put the import lib
# urls.py
from django.urls import path
from security.views import AuditEventListView, CommentModerationView

urlpatterns = [
    path("audit-events/", AuditEventListView.as_view(), name="audit_events"),
    path("comments_moderate/", CommentModerationView.as_view(), name="comment_moderate"),
]
