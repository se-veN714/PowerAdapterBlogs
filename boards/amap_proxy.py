"""Fixed-target proxy used by AMap Web JS API security serviceHost."""

import hashlib
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET


_SAFE_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")
_SAFE_CALLBACK = re.compile(
    r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$"
)
_ALLOWED_RESOURCES = frozenset(
    {
        "v3/assistant/inputtips",
        "v3/geocode/regeo",
        "v3/place/text",
    }
)


def _rate_limit_key(request) -> str:
    client_ip = str(
        getattr(request, "client_ip", request.META.get("REMOTE_ADDR", "unknown"))
    )
    digest = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:24]
    minute = int(time.time() // 60)
    return f"amap-proxy:{digest}:{minute}"


def _within_rate_limit(request) -> bool:
    limit = max(1, settings.AMAP_PROXY_REQUESTS_PER_MINUTE)
    key = _rate_limit_key(request)
    if cache.add(key, 1, timeout=70):
        return True
    return cache.incr(key) <= limit


@require_GET
def amap_service_proxy(request, resource=""):
    if not (
        settings.AMAP_JS_API_ENABLED
        and settings.AMAP_JS_SECURITY_JSCODE
        and resource
        and _SAFE_PATH.fullmatch(resource)
        and ".." not in resource
        and resource in _ALLOWED_RESOURCES
    ):
        raise Http404

    if len(request.META.get("QUERY_STRING", "")) > 4096:
        return HttpResponse("AMap request query is too large", status=400)
    callback = request.GET.get("callback", "")
    if callback and not _SAFE_CALLBACK.fullmatch(callback):
        return HttpResponse("Invalid AMap callback", status=400)
    if not _within_rate_limit(request):
        response = HttpResponse("AMap request rate exceeded", status=429)
        response["Retry-After"] = "60"
        return response

    query = request.GET.copy()
    query["jscode"] = settings.AMAP_JS_SECURITY_JSCODE
    if callback:
        query["callback"] = callback
    target = f"https://restapi.amap.com/{resource}?{query.urlencode()}"
    try:
        upstream = urlopen(
            Request(target, headers={"User-Agent": "PowerAdapterBlogs-AMap/1.0"}),
            timeout=6,
        )
        max_bytes = max(1024, settings.AMAP_PROXY_MAX_RESPONSE_BYTES)
        body = upstream.read(max_bytes + 1)
        if len(body) > max_bytes:
            return HttpResponse("AMap upstream response is too large", status=502)
        content_type = upstream.headers.get("Content-Type", "application/json")
        # JSAPI 部分服务（如 AutoComplete inputtips）走 JSONP：body 是 callback(...) 的
        # JS 代码，经 <script> 标签执行。上游即使带 callback 也返回 application/json，
        # 叠加全站 X-Content-Type-Options: nosniff 后浏览器会以 MIME 不可执行为由拒绝
        # 执行该脚本，插件拿不到数据（下拉空且隐藏）。此处对 JSONP 响应改写为可执行类型。
        if callback:
            content_type = "application/javascript; charset=utf-8"
        response = HttpResponse(body, content_type=content_type, status=upstream.status)
        response["Cache-Control"] = "private, max-age=60"
        return response
    except HTTPError as exc:
        return HttpResponse("AMap upstream rejected request", status=exc.code)
    except (URLError, TimeoutError):
        return HttpResponse("AMap upstream unavailable", status=502)
