# -*- coding: utf-8 -*-
# @File    : settings/base.py
# @Time    : 2025/2/3 20:09
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了基本的Django设置功能的类和函数。
"""

import json
import os
from pathlib import Path

# here put the import lib
"""
Django settings for PowerAdapterBlogs project.

Originally generated with Django 5.1.5; runtime target is Django 5.2 LTS.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.1/ref/settings/
"""

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# 生产环境务必通过环境变量注入 SECRET_KEY，此处仅为开发环境兜底
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY", "django-insecure-dev-fallback--change-me-in-production"
)
if SECRET_KEY.startswith("django-insecure-dev-fallback"):
    import warnings

    warnings.warn(
        "SECRET_KEY is using the dev fallback! Set DJANGO_SECRET_KEY env var in production.",
        RuntimeWarning,
    )

# Application definition

INSTALLED_APPS = [
    "jazzmin",
    "dal",
    "dal_select2",
    "PowerAdapterBlogs.admin_config.SuperuserAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "widget_tweaks",
    "drf_spectacular",
    "django_redis",
    # my_app
    "security.apps.SecurityConfig",
    "Blogs",
    "config",
    "comment",
    "accounts",
    "boards.apps.BoardsConfig",
    "moderation.apps.ModerationConfig",
    "operations.apps.OperationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "comment.middleware.ClientMetaMiddleware",
    "Blogs.middleware.user_id.UserIdMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.PrivilegedSingleSessionMiddleware",
    "accounts.middleware.MtlsAdminMiddleware",
    "accounts.middleware.MfaPrivilegeMiddleware",
    "accounts.middleware.RequestUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "PowerAdapterBlogs.urls"

THEMES = "devenir"  # 更改切换主题

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "themes" / THEMES / "templates",
            BASE_DIR / "themes" / THEMES,
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.static",
                "boards.views.boards_context",
                "config.context_processors.public_site_metadata",
                "accounts.context_processors.account_security_navigation",
                "operations.context_processors.operations_context",
            ],
        },
    },
]

WSGI_APPLICATION = "PowerAdapterBlogs.wsgi.application"

# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_USER_MODEL = "accounts.MyUser"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"

USE_I18N = True

USE_L10N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = "/static/"

STATIC_ROOT = BASE_DIR / "common_static"

STATICFILES_DIRS = [
    BASE_DIR / "static",
    BASE_DIR / "themes" / THEMES / "static",
]

MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media/"

# ---------------------------------------------------------------------------
# Skateboard Clip 媒体流水线（SK8 S0）
# 约束集中于此，禁止散落硬编码；生产可用环境独立 settings 覆盖。
# ---------------------------------------------------------------------------

# 单条上传大小上限（字节）：150 MiB（建议值，可按部署调整）。
SKATE_CLIP_MAX_UPLOAD_BYTES = 150 * 1024 * 1024

# 单条真实时长硬限制（毫秒）：20 秒（FFprobe 权威裁决）。
SKATE_CLIP_MAX_DURATION_MS = 20_000

# 私有原片根目录：刻意放在 MEDIA_ROOT 之外——开发环境 urls.py 会用
# static() 服务整个 MEDIA_ROOT，生产 Nginx 亦只放行派生目录；私有原片
# 在两个面都不可达，且 Storage.url() 直接抛错。
SKATE_CLIP_SOURCE_ROOT = BASE_DIR / "media-private" / "skateboard" / "source"

# 派生资源（delivery/preview/poster）根目录与公开 URL 前缀：
# 位于 MEDIA_ROOT 下由 /media/ 前缀统一分发；生产 Nginx 需对
# /media/skate/ 仅放行派生子目录并禁列目录。
SKATE_CLIP_DELIVERY_ROOT = MEDIA_ROOT / "skate"
SKATE_CLIP_DELIVERY_URL = f"{MEDIA_URL}skate/"

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

JAZZMIN_SETTINGS = {
    "site_title": "PowerAdapter 后台",
    "site_header": "PowerAdapter 控制台",
    "site_brand": "PowerAdapter",
    "welcome_sign": "登录 PowerAdapter 控制台",
    "site_logo": "img/PowerAdapter_icon.webp",
    "login_logo": "img/PowerAdapter_logo.webp",
    "site_logo_classes": "poweradapter-logo",
    "site_icon": "img/PowerAdapter_icon.webp",
    "copyright": "PowerAdapter · 内容与秩序",
    "topmenu_links": [
        {"name": "返回网站", "url": "/", "new_window": True},
    ],
    "show_sidebar": True,
    "navigation_expanded": False,
    "order_with_respect_to": [
        "Blogs",
        "comment",
        "boards",
        "accounts",
        "security",
    ],
    "icons": {
        "Blogs": "fas fa-pen-nib",
        "Blogs.post": "fas fa-file-alt",
        "Blogs.category": "fas fa-folder-open",
        "Blogs.tag": "fas fa-tags",
        "Blogs.postrevision": "fas fa-history",
        "comment": "fas fa-comments",
        "comment.comment": "fas fa-comment-dots",
        "boards": "fas fa-layer-group",
        "boards.board": "fas fa-columns",
        "boards.boardmembership": "fas fa-user-friends",
        "accounts": "fas fa-users-cog",
        "accounts.myuser": "fas fa-user",
        "security": "fas fa-shield-alt",
        "security.securelogentry": "fas fa-fingerprint",
        "admin.logentry": "fas fa-clipboard-list",
    },
    "default_icon_parents": "far fa-folder",
    "default_icon_children": "far fa-circle",
    "custom_css": "css/admin_theme.css",
    "use_google_fonts_cdn": False,
    "show_ui_builder": False,
    "changeform_format": "horizontal_tabs",
}

JAZZMIN_UI_TWEAKS = {
    "accent": "accent-light",
    "navbar": "navbar-dark",
    "no_navbar_border": True,
    "navbar_fixed": True,
    "sidebar": "sidebar-dark-primary",
    "sidebar_fixed": True,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": True,
    "sidebar_nav_flat_style": True,
    "theme": "darkly",
    "dark_mode_theme": None,
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 10,  # 后续可以尝试 Cursor分页
}
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

info_format = "[{asctime}] INFO (✿◕‿◕) {message}"
warn_format = "[{asctime}] WARN (ಠ_ಠ) {message}"
error_format = "[{asctime}] ERROR (╯°□°）╯︵ ┻━┻ {message}"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "info": {"format": info_format, "style": "{"},
        "warning": {"format": warn_format, "style": "{"},
        "error": {"format": error_format, "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "info",
        },
        "info_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "info.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "info",
            "level": "INFO",
            "encoding": "utf-8",
        },
        "warning_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "warning.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "warning",
            "level": "WARNING",
            "encoding": "utf-8",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "error.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "error",
            "level": "ERROR",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "Blogs": {
            "handlers": ["info_file", "warning_file", "error_file"],
            "level": "DEBUG",
            "propagate": False,  # 阻止再传给 root
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG",
    },
}

REDIS_CACHE_URL = "redis://127.0.0.1:6379/1"
REDIS_SESSIONS_URL = "redis://127.0.0.1:6379/2"

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_CACHE_URL,
        "TIMEOUT": 300,
        "OPTIONS": {
            # 'PASSWORD':'<password>'
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
        "CONNECTION_POOL_CLASS": "redis.connection.BlockingConnectionPool",
    },
    "sessions": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_SESSIONS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    },
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "sessions"

# 滥用防护（均使用默认 cache，可通过环境专属 settings 覆盖）
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60
COMMENT_RATE_LIMIT = 5
COMMENT_RATE_WINDOW = 60

# 邮件与邀请制账号。生产环境在 product.py 中强制从环境变量提供实际值。
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "http://127.0.0.1:8000")
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "PowerAdapter <webmaster@localhost>"
)
SECURITY_CONTACT_EMAIL = os.getenv("SECURITY_CONTACT_EMAIL", "sevencdxxiv@qq.com")
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
ACCOUNT_INVITATION_TTL_SECONDS = 24 * 60 * 60
ACCOUNT_VERIFIED_GROUP_NAME = "VerifiedUsers"
PASSWORD_EMAIL_CODE_TTL_SECONDS = 10 * 60
PASSWORD_EMAIL_SEND_COOLDOWN_SECONDS = 60
PASSWORD_EMAIL_SEND_WINDOW_SECONDS = 60 * 60
PASSWORD_EMAIL_MAX_SENDS = 3
PASSWORD_EMAIL_MAX_ATTEMPTS = 5
PASSWORD_EMAIL_VERIFIED_TTL_SECONDS = 10 * 60


def _json_object_env(name):
    """Parse a JSON object without reflecting secret configuration in errors."""
    raw_value = os.getenv(name, "")
    if not raw_value:
        return {}
    try:
        value = json.loads(raw_value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be a valid JSON object.") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} must be a valid JSON object.")
    return value


# Versioned AES-256-GCM keyring. An empty keyring keeps MFA enrollment disabled;
# accounts.authn.mfa_services fails closed before it generates or persists a seed.
MFA_TOTP_KEYRING = _json_object_env("MFA_TOTP_KEYRING_JSON")
MFA_TOTP_ACTIVE_KEY_ID = os.getenv("MFA_TOTP_ACTIVE_KEY_ID", "")
MFA_TOTP_ISSUER = os.getenv("MFA_TOTP_ISSUER", "PowerAdapter")
MFA_TOTP_BINDING_TTL_SECONDS = 10 * 60
MFA_TOTP_VALID_WINDOW = 1
MFA_RECOVERY_CODE_COUNT = 10
MFA_ENFORCEMENT_ENABLED = os.getenv("MFA_ENFORCEMENT_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
}
MFA_CHALLENGE_TTL_SECONDS = 5 * 60
MFA_CHALLENGE_MAX_ATTEMPTS = 5
MFA_CHALLENGE_COOLDOWN_SECONDS = 15 * 60
MFA_PRIVILEGED_SESSION_TTL_SECONDS = 15 * 60
MFA_SUPER_ADMIN_IDLE_TTL_SECONDS = 5 * 60
MFA_DASHBOARD_REMEMBER_TTL_SECONDS = 7 * 24 * 60 * 60
MEMBERSHIP_STEP_UP_TTL_SECONDS = 5 * 60

# H3 TLS 1.3 mTLS application boundary. Nginx must clear and replace every
# X-PA-* header. Production readiness accepts only the standard-tls profile;
# SM2/TLCP is an isolated experiment and is not a production authentication path.
# The feature stays disabled until an independent admin vhost, trusted proxy
# network and shared proxy authentication secret have been configured.
MTLS_ENFORCEMENT_ENABLED = os.getenv("MTLS_ENFORCEMENT_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
}
MTLS_ADMIN_HOST = os.getenv("MTLS_ADMIN_HOST", "")
MTLS_TRUSTED_PROXY_NETWORKS = tuple(
    item.strip()
    for item in os.getenv("MTLS_TRUSTED_PROXY_NETWORKS", "").split(",")
    if item.strip()
)
MTLS_TRUST_UNIX_SOCKET_PROXY = os.getenv(
    "MTLS_TRUST_UNIX_SOCKET_PROXY", "false"
).lower() in {"1", "true", "yes"}
MTLS_PROXY_AUTH_SECRET = os.getenv("MTLS_PROXY_AUTH_SECRET", "")
MTLS_CERTIFICATE_PROFILE = os.getenv("MTLS_CERTIFICATE_PROFILE", "")
SUPER_ADMIN_EXTERNAL_URL = os.getenv("SUPER_ADMIN_EXTERNAL_URL", "")

MONGO = {
    "HOST": os.getenv("MONGO_HOST", "localhost"),
    "PORT": os.getenv("MONGO_PORT", 27017),
    "DB_NAME": os.getenv("MONGO_DB_NAME", "poweradapter_mongo"),
    "DB_USER": os.getenv("MONGO_DB_USER", ""),
    "DB_PASSWORD": os.getenv("MONGO_DB_PASSWORD", ""),
    "COLLECTION": os.getenv("MONGO_COLLECTION", "logs"),
}
