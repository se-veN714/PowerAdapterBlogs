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
from .base import *  # NOQA

# here put the import lib

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }

}

INSTALLED_APPS += [
    "debug_toolbar",
]

MIDDLEWARE = ['debug_toolbar.middleware.DebugToolbarMiddleware'] + MIDDLEWARE

INTERNAL_IPS = ['127.0.0.1']

LOG_HMAC_KEY = b'\x9dM\xb0\x01ss_>\xb3\xec\xb5w\xa1\xb3kY\xc3\xa4\x19\xb7\x8cE\xf3\xff};\x01by\xa7\xa22'
