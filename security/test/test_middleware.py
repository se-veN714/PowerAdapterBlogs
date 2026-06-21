# -*- coding: utf-8 -*-
# @File    : test_middleware.py
# @Time    : 2026/1/29 18:59
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了中间件测试功能的类和函数。
"""
# security/tests/test_middleware.py

# here put the import lib
from django.test import TestCase, Client
from django.test.utils import override_settings


@override_settings(ROOT_URLCONF="security.test.t_urls")
class ClientMetaMiddlewareTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = "/test/echo/"
        self.base_headers = {
            "HTTP_X_FORWARDED_FOR": "203.0.113.10, 9.9.9.9",
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_USER_AGENT": "DjangoTestClient/0.1",
            "HTTP_REFERER": "https://example.com/from-test",
            "HTTP_ACCEPT_LANGUAGE": "en-US",
        }

    def _get(self, **overrides):
        headers = {**self.base_headers, **overrides}
        return self.client.get(self.url, **headers)

    def test_client_meta_basic_header(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # 来自 ClientMetaMiddleware 注入的数据
        self.assertEqual(data["ip"], "203.0.113.10")
        self.assertEqual(data["ua"], "DjangoTestClient/0.1")
        self.assertEqual(data["referrer"], "https://example.com/from-test")
        self.assertEqual(data["path"], "/test/echo/")

        # 指纹存在性检查
        self.assertIsNotNone(data["fp"])
        self.assertTrue(len(data["fp"]) > 0)
