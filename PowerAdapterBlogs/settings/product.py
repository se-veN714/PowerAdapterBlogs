# -*- coding: utf-8 -*-
# @File    : product.py
# @Time    : 2025/2/3 20:09
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了上线时正式的设置
"""
# ruff: noqa: F403, F405

# here put the import lib
import base64
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *

DEBUG = False


def required_env(name):
    value = os.getenv(name)
    if not value:
        raise ImproperlyConfigured(f'生产环境必须设置 {name}')
    return value


SECRET_KEY = required_env('DJANGO_SECRET_KEY')
ALLOWED_HOSTS = [host.strip() for host in required_env('DJANGO_ALLOWED_HOSTS').split(',') if host.strip()]

PUBLIC_SITE_URL = required_env('PUBLIC_SITE_URL')
DEFAULT_FROM_EMAIL = required_env('DEFAULT_FROM_EMAIL')
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = required_env('EMAIL_HOST')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '465'))
EMAIL_HOST_USER = required_env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = required_env('EMAIL_HOST_PASSWORD')
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'true').lower() in {'1', 'true', 'yes'}
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'false').lower() in {'1', 'true', 'yes'}
if EMAIL_USE_SSL and EMAIL_USE_TLS:
    raise ImproperlyConfigured('EMAIL_USE_SSL 与 EMAIL_USE_TLS 不能同时启用')

DATABASES = {
    "default": {
        'ENGINE': "django.db.backends.postgresql",
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT'),
    }
}

key_base64 = required_env('LOGINTEGRITY_HMAC_KEY_BASE64')
try:
    LOG_HMAC_KEY = base64.b64decode(key_base64, validate=True)
except (ValueError, TypeError) as exc:
    raise ImproperlyConfigured('LOGINTEGRITY_HMAC_KEY_BASE64 不是有效 Base64') from exc
if len(LOG_HMAC_KEY) < 32:
    raise ImproperlyConfigured('LOGINTEGRITY_HMAC_KEY_BASE64 解码后至少需要 32 bytes')

CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_REFERRER_POLICY = 'same-origin'

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]

# 仅在可信反向代理确实覆盖 X-Forwarded-Proto 时启用。
if os.getenv('DJANGO_TRUST_X_FORWARDED_PROTO', '').lower() in {'1', 'true', 'yes'}:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
