# -*- coding: utf-8 -*-
# @File    : settings/develop.py
# @Time    : 2025/2/3 20:09
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了开发环境下的设置
"""
import base64
import os

from .base import *  # NOQA

# here put the import lib

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }

}

INSTALLED_APPS += [  # noqa: F405
    "debug_toolbar",
]

MIDDLEWARE = ['debug_toolbar.middleware.DebugToolbarMiddleware'] + MIDDLEWARE  # noqa: F405

INTERNAL_IPS = ['127.0.0.1']

# 本地 Nginx mTLS 入口终止 TLS 后通过 loopback 转发给 Waitress。
# 保留外部 HTTPS scheme/Origin，避免管理登录被 CSRF 同源检查拒绝。
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_TRUSTED_ORIGINS = ['https://admin.localhost:8443']
SUPER_ADMIN_EXTERNAL_URL = 'https://admin.localhost:8443/super_admin/'

# WhiteNoise — 开发环境自动检测静态文件变更，无需 collectstatic
WHITENOISE_AUTOREFRESH = True

# HMAC 密钥：优先从环境变量读取，开发环境提供硬编码兜底
_key_b64 = os.getenv('LOGINTEGRITY_HMAC_KEY_BASE64')
if _key_b64:
    LOG_HMAC_KEY = base64.b64decode(_key_b64)
else:
    LOG_HMAC_KEY = b'\x9dM\xb0\x01ss_>\xb3\xec\xb5w\xa1\xb3kY\xc3\xa4\x19\xb7\x8cE\xf3\xff};\x01by\xa7\xa22'
