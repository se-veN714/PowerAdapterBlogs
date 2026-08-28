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
ERROR_PREVIEW_ENABLED = False


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
        'NAME': required_env('DB_NAME'),
        'USER': required_env('DB_USER'),
        'PASSWORD': required_env('DB_PASSWORD'),
        'HOST': required_env('DB_HOST'),
        'PORT': required_env('DB_PORT'),
    }
}

required_env('REDIS_CACHE_URL')
required_env('REDIS_SESSIONS_URL')
required_env('MONGO_HOST')
required_env('MONGO_DB_NAME')
required_env('MONGO_DB_USER')
required_env('MONGO_DB_PASSWORD')
required_env('MONGO_REPLICA_SET')

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

LOGGING["root"]["level"] = "INFO"
LOGGING["loggers"]["Blogs"]["handlers"].append("console")
LOGGING["loggers"]["Blogs"]["level"] = "INFO"
LOGGING["loggers"]["security"]["handlers"].append("console")

key_base64 = required_env('LOGINTEGRITY_HMAC_KEY_BASE64')
try:
    LOG_HMAC_KEY = base64.b64decode(key_base64, validate=True)
except (ValueError, TypeError) as exc:
    raise ImproperlyConfigured('LOGINTEGRITY_HMAC_KEY_BASE64 不是有效 Base64') from exc
if len(LOG_HMAC_KEY) < 32:
    raise ImproperlyConfigured('LOGINTEGRITY_HMAC_KEY_BASE64 解码后至少需要 32 bytes')


def required_audit_key(name):
    try:
        key = base64.b64decode(required_env(name), validate=True)
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(f'{name} 不是有效 Base64') from exc
    if len(key) != 32:
        raise ImproperlyConfigured(f'{name} 解码后必须正好为 32 bytes')
    return key


MONGO_AUDIT_ACTIVE_KEY_ID = os.getenv('MONGO_AUDIT_ACTIVE_KEY_ID', 'mongo-v1')
CHECKPOINT_AUDIT_ACTIVE_KEY_ID = os.getenv('CHECKPOINT_AUDIT_ACTIVE_KEY_ID', 'checkpoint-v1')
MONGO_AUDIT_LEGACY_KEY_ID = 'legacy-mongo-v0'
MONGO_AUDIT_HMAC_KEYS = {
    MONGO_AUDIT_ACTIVE_KEY_ID: required_audit_key('MONGO_AUDIT_HMAC_KEY_BASE64'),
    MONGO_AUDIT_LEGACY_KEY_ID: LOG_HMAC_KEY,
}
CHECKPOINT_AUDIT_HMAC_KEYS = {
    CHECKPOINT_AUDIT_ACTIVE_KEY_ID: required_audit_key('CHECKPOINT_AUDIT_HMAC_KEY_BASE64'),
}
active_audit_keys = {
    MONGO_AUDIT_HMAC_KEYS[MONGO_AUDIT_ACTIVE_KEY_ID],
    CHECKPOINT_AUDIT_HMAC_KEYS[CHECKPOINT_AUDIT_ACTIVE_KEY_ID],
}
if len(active_audit_keys) != 2 or LOG_HMAC_KEY in active_audit_keys:
    raise ImproperlyConfigured(
        'MongoDB 与 checkpoint 活跃审计密钥必须相互独立且不同于历史密钥'
    )

if not MFA_ENFORCEMENT_ENABLED:
    raise ImproperlyConfigured('生产环境必须启用 MFA_ENFORCEMENT_ENABLED')
if not MTLS_ENFORCEMENT_ENABLED:
    raise ImproperlyConfigured('生产环境必须启用 MTLS_ENFORCEMENT_ENABLED')
required_env('MTLS_ADMIN_HOST')
required_env('MTLS_TRUSTED_PROXY_NETWORKS')
mtls_proxy_secret = required_env('MTLS_PROXY_AUTH_SECRET')
if len(mtls_proxy_secret) < 32:
    raise ImproperlyConfigured('MTLS_PROXY_AUTH_SECRET 至少需要 32 个字符')
if required_env('MTLS_CERTIFICATE_PROFILE') != 'standard-tls':
    raise ImproperlyConfigured('生产 mTLS 只接受 standard-tls profile')
required_env('SUPER_ADMIN_EXTERNAL_URL')

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
if os.getenv('DJANGO_TRUST_X_FORWARDED_PROTO', '').lower() not in {'1', 'true', 'yes'}:
    raise ImproperlyConfigured('生产反向代理必须启用 DJANGO_TRUST_X_FORWARDED_PROTO')
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
