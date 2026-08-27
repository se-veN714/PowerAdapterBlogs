"""AMap serviceHost 代理视图测试。

重点回归：JSONP 响应（带 callback 参数）必须改写为可执行 Content-Type，
否则在全站 X-Content-Type-Options: nosniff 下浏览器会拒绝执行，
导致 AutoComplete 拿不到数据（候选下拉空且隐藏）。
"""

from unittest import mock

from django.test import TestCase, override_settings

from boards.amap_proxy import amap_service_proxy


def _fake_upstream(content_type="application/json", body=b'{"status": "1"}'):
    upstream = mock.Mock()
    upstream.status = 200
    upstream.read.return_value = body
    upstream.headers = {"Content-Type": content_type}
    return upstream


@override_settings(AMAP_JS_API_ENABLED=True, AMAP_JS_SECURITY_JSCODE="j" * 32)
class AmapServiceProxyTests(TestCase):
    """经 /_AMapService/<resource> 的代理行为。"""

    def _upstream_target(self, urlopen_mock):
        request = urlopen_mock.call_args[0][0]
        return request.full_url

    def test_jsonp_response_gets_executable_content_type(self):
        """带 callback 的响应须返回 application/javascript，绕过 nosniff 对 JSONP 的拦截。"""
        with mock.patch("boards.amap_proxy.urlopen") as urlopen_mock:
            urlopen_mock.return_value = _fake_upstream("application/json")
            response = self.client.get(
                "/_AMapService/v3/assistant/inputtips",
                {"keywords": "kunming", "callback": "jsonp_1", "key": "abc"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"], "application/javascript; charset=utf-8"
        )

    def test_plain_json_response_keeps_upstream_content_type(self):
        """不带 callback 的普通 JSON 响应保持上游类型不变。"""
        with mock.patch("boards.amap_proxy.urlopen") as urlopen_mock:
            urlopen_mock.return_value = _fake_upstream("application/json")
            response = self.client.get(
                "/_AMapService/v3/geocode/regeo", {"location": "1,2", "key": "abc"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/json"))

    def test_jscode_appended_and_query_forwarded(self):
        """转发须保留原 query 并在服务端追加 jscode。"""
        with mock.patch("boards.amap_proxy.urlopen") as urlopen_mock:
            urlopen_mock.return_value = _fake_upstream()
            self.client.get(
                "/_AMapService/v3/assistant/inputtips", {"keywords": "k", "key": "abc"}
            )
        target = self._upstream_target(urlopen_mock)
        self.assertIn("https://restapi.amap.com/v3/assistant/inputtips", target)
        self.assertIn("key=abc", target)
        self.assertIn("jscode=" + "j" * 32, target)

    def test_disabled_returns_404(self):
        """开关关闭时代理整体 404。"""
        with override_settings(AMAP_JS_API_ENABLED=False):
            response = self.client.get(
                "/_AMapService/v3/assistant/inputtips", {"keywords": "k"}
            )
        self.assertEqual(response.status_code, 404)

    def test_unsafe_resource_returns_404(self):
        """非法 resource 段直接 404，不触达上游。"""
        response = self.client.get("/_AMapService/v3/../etc/passwd")
        self.assertEqual(response.status_code, 404)

    def test_unneeded_but_safe_resource_returns_404(self):
        """代理只开放当前 UI 实际使用的资源，不提供通用高德凭据转发。"""
        response = self.client.get("/_AMapService/v3/weather/weatherInfo")
        self.assertEqual(response.status_code, 404)

    def test_unsafe_jsonp_callback_is_rejected_before_upstream(self):
        with mock.patch("boards.amap_proxy.urlopen") as urlopen_mock:
            response = self.client.get(
                "/_AMapService/v3/assistant/inputtips",
                {"keywords": "k", "callback": "alert(1)//"},
            )
        self.assertEqual(response.status_code, 400)
        urlopen_mock.assert_not_called()

    @override_settings(AMAP_PROXY_REQUESTS_PER_MINUTE=1)
    def test_per_client_rate_limit_rejects_burst(self):
        with mock.patch("boards.amap_proxy.urlopen") as urlopen_mock:
            urlopen_mock.return_value = _fake_upstream()
            first = self.client.get(
                "/_AMapService/v3/geocode/regeo",
                {"location": "1,2"},
                REMOTE_ADDR="198.51.100.23",
            )
            second = self.client.get(
                "/_AMapService/v3/geocode/regeo",
                {"location": "1,2"},
                REMOTE_ADDR="198.51.100.23",
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second["Retry-After"], "60")

    def test_upstream_unavailable_returns_502(self):
        """上游不可达时返回 502。"""
        from urllib.error import URLError

        with mock.patch(
            "boards.amap_proxy.urlopen", side_effect=URLError("no route to host")
        ):
            response = self.client.get(
                "/_AMapService/v3/assistant/inputtips", {"keywords": "k", "key": "a"}
            )
        self.assertEqual(response.status_code, 502)


class AmapServiceProxyDirectTests(TestCase):
    """直接调用视图函数，验证 callback 判定只看 GET 参数。"""

    @override_settings(AMAP_JS_API_ENABLED=True, AMAP_JS_SECURITY_JSCODE="j" * 32)
    def test_callback_param_only_in_query_triggers_override(self):
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get(
            "/_AMapService/v3/assistant/inputtips?keywords=k&callback=cb"
        )
        with mock.patch("boards.amap_proxy.urlopen") as urlopen_mock:
            urlopen_mock.return_value = _fake_upstream("application/json")
            response = amap_service_proxy(request, "v3/assistant/inputtips")
        self.assertEqual(
            response["Content-Type"], "application/javascript; charset=utf-8"
        )
