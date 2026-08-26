"""Read-only MongoDB audit deployment smoke check.

This helper intentionally never writes, deletes, or prints audit payloads. Use
the management commands for bounded partition verification and checkpointing.
"""
# ruff: noqa: E402
import os
import sys
import logging

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 抑制 pymongo 的 INFO 日志噪音
logging.disable(logging.CRITICAL)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PowerAdapterBlogs.settings.develop")
import django
django.setup()

from security.mongo_client import MongoLogger


def run():
    print("=" * 50)
    print("MongoDB 安全审计部署只读检查")
    print("=" * 50)

    m = MongoLogger()

    try:
        result = m.check_deployment()
        print(f"PASS topology={result['topology']} status={result['status']}")
        print("使用 audit_log_integrity --mongo --partition <partition> 做有界验链。")
    finally:
        m.close()


if __name__ == "__main__":
    run()
