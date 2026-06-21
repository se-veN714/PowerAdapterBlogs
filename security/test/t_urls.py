# -*- coding: utf-8 -*-
# @File    : t_urls.py
# @Time    : 2026/1/29 18:48
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了测试专用的url功能的类和函数。
"""

# here put the import lib
from django.urls import path
from django.http import JsonResponse



def echo_client_meta(request):
    return JsonResponse({
        'ip': getattr(request, 'client_ip', None),
        'ua': getattr(request, 'client_ua', None),  # ua: user_agent
        'referrer': getattr(request, 'client_referrer', None),
        'path': getattr(request, 'client_path', None),
        'fp': getattr(request, 'client_fp', None),
    })

urlpatterns = [
    path('test/echo/', echo_client_meta),
]
