"""Use a configured canonical origin; never derive OAuth audiences from Host input."""
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

SCOPES = {
    'padif:read': '读取 PAdif 文档、版本、分支、差异和批注',
    'padif:annotate': '添加批注、回复，以及填写已处理或驳回说明',
    'padif:version': '创建改稿分支，并向指定分支追加版本（不含发布主线）',
}


def origin():
    value = settings.PUBLIC_SITE_URL.rstrip('/')
    parsed = urlsplit(value)
    if not parsed.hostname or any(char.isspace() for char in value):
        raise ImproperlyConfigured('PUBLIC_SITE_URL must include a valid host.')
    try:
        parsed.port
    except ValueError as error:
        raise ImproperlyConfigured('PUBLIC_SITE_URL has an invalid port.') from error
    local = parsed.hostname in {'127.0.0.1', 'localhost', '::1'}
    if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ImproperlyConfigured('PUBLIC_SITE_URL must be an origin without a path or credentials.')
    if parsed.scheme != 'https' and not (settings.DEBUG and local and parsed.scheme == 'http'):
        raise ImproperlyConfigured('PAdif OAuth requires HTTPS; HTTP is only allowed for local development.')
    return value


def resource():
    return origin() + '/padif/mcp/'
