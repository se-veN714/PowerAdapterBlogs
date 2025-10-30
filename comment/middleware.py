# -*- coding: utf-8 -*-
# @File    : middleware.py
# @Time    : 2025/9/2 05:33
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了comment的中间件功能的类和函数。
"""

# here put the import lib
from django.utils.deprecation import MiddlewareMixin

from ipaddress import ip_address
from gmssl import sm3, func

TRUSTED_PROXY_COUNT = 1  # Nginx/反代层数；自行按部署修改
TRUSTED_PROXY_HEADERS = ["HTTP_X_FORWARDED_FOR", "HTTP_X_REAL_IP"]

def get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        # 取链上倒数第 TRUSTED_PROXY_COUNT+1 个，避免伪造
        parts = [p.strip() for p in xff.split(",")]
        if len(parts) > TRUSTED_PROXY_COUNT:
            candidate = parts[-(TRUSTED_PROXY_COUNT+1)]
        else:
            candidate = parts[0]
        try:
            ip_address(candidate)
            return candidate
        except ValueError:
            pass
    # 兜底 REMOTE_ADDR
    return request.META.get("REMOTE_ADDR")

class ClientMetaMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.client_ip = get_client_ip(request)
        request.client_ua = request.META.get("HTTP_USER_AGENT", "")
        request.client_referrer = request.META.get("HTTP_REFERER", "")
        request.client_path = request.path
        # 可构造一个弱指纹（避免直接存组合原文）
        fp_seed = f"{request.client_ua}|{request.client_ip}|{request.META.get('HTTP_ACCEPT_LANGUAGE','')}"
        request.client_fp = sm3.sm3_hash(func.bytes_to_list(bytes(fp_seed, encoding="utf-8")))
