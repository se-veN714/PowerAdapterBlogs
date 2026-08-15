"""Fixed-target proxy used by AMap Web JS API security serviceHost."""

import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET


_SAFE_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")


@require_GET
def amap_service_proxy(request, resource=""):
    if not (
        settings.AMAP_JS_API_ENABLED
        and settings.AMAP_JS_SECURITY_JSCODE
        and resource
        and _SAFE_PATH.fullmatch(resource)
        and ".." not in resource
    ):
        raise Http404

    query = request.GET.copy()
    query["jscode"] = settings.AMAP_JS_SECURITY_JSCODE
    target = f"https://restapi.amap.com/{resource}?{query.urlencode()}"
    try:
        upstream = urlopen(
            Request(target, headers={"User-Agent": "PowerAdapterBlogs-AMap/1.0"}),
            timeout=6,
        )
        body = upstream.read()
        content_type = upstream.headers.get("Content-Type", "application/json")
        return HttpResponse(body, content_type=content_type, status=upstream.status)
    except HTTPError as exc:
        return HttpResponse("AMap upstream rejected request", status=exc.code)
    except (URLError, TimeoutError):
        return HttpResponse("AMap upstream unavailable", status=502)
