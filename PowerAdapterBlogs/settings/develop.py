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

# WhiteNoise — 开发环境自动检测静态文件变更，无需 collectstatic
WHITENOISE_AUTOREFRESH = True

# HMAC 密钥：优先从环境变量读取，开发环境提供硬编码兜底
_key_b64 = os.getenv('LOGINTEGRITY_HMAC_KEY_BASE64')
if _key_b64:
    LOG_HMAC_KEY = base64.b64decode(_key_b64)
else:
    LOG_HMAC_KEY = b'\x9dM\xb0\x01ss_>\xb3\xec\xb5w\xa1\xb3kY\xc3\xa4\x19\xb7\x8cE\xf3\xff};\x01by\xa7\xa22'
