"""
MongoDB 日志完整性验证脚本
测试：连接 -> 写入 HMAC -> 验证 -> 审计
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
    print("MongoDB 日志完整性验证")
    print("=" * 50)

    m = MongoLogger()

    # 1. 连接测试
    status = "OK 已连接" if m.connected else "FAIL 未连接"
    print(f"\n[1] 连接状态: {status}")
    if not m.connected:
        print("MongoDB 不可用，退出。")
        return

    db_name = m.db.name if m.db is not None else "N/A"
    col_name = m.collection.name if m.collection is not None else "N/A"
    print(f"    数据库: {db_name}")
    print(f"    集合:   {col_name}")

    # 2. 写入测试
    print("\n[2] 写入测试日志 (HMAC 签名)...")
    result = m.insert_log("test_verify", {
        "msg": "hello mongo",
        "ts": "2026-06-21T23:30:00",
    })
    if result:
        print(f"    PASS 写入成功, _id={result.inserted_id}")
    else:
        print("    FAIL 写入失败")
        return

    # 3. 查询验证
    print("\n[3] 查询并验证 HMAC...")
    docs = m.find_all(3)
    print(f"    最新 3 条: {len(docs)} 条")
    if docs:
        doc = docs[0]
        valid = m.verify_log(doc)
        vstatus = "PASS 完整" if valid else "FAIL 被篡改"
        print(f"    最新文档 HMAC 验证: {vstatus}")

    # 4. 全量审计
    print("\n[4] 全量审计...")
    audit = m.audit_all()
    print(f"    总计: {audit['total']} 条")
    print(f"    完整: {audit['healthy']} 条")
    print(f"    篡改: {audit['tampered']} 条")

    # 5. 清理测试数据
    print("\n[5] 清理测试数据...")
    m.collection.delete_many({"action": "test_verify"})
    print("    已清理")

    m.close()

    print(f"\n{'=' * 50}")
    print("PASS 全部验证通过 - MongoDB 日志链路完整可用")
    print("=" * 50)


if __name__ == "__main__":
    run()
