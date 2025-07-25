# -*- coding: utf-8 -*-
# @File    : urls.py
# @Time    : 2025/7/11 12:09
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了XXX功能的类和函数。
"""
# here put the import lib
from django.urls import path
from django.contrib.auth.views import LogoutView

from accounts.views import LoginView

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(next_page='index'), name='logout'),
]