"""基于受信配置生成公开站点绝对 URL。"""

from urllib.parse import urljoin

from django.conf import settings


def public_absolute_url(path):
    base_url = settings.PUBLIC_SITE_URL.rstrip("/") + "/"
    return urljoin(base_url, path.lstrip("/"))
