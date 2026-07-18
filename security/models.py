import json
from datetime import UTC
from hmac import compare_digest

from django.contrib.admin.models import LogEntry
from django.db import models
from django.utils import timezone

from security.sec_utils.hmac_utils import sm3_hmac


class SecureLogEntry(models.Model):
    PAYLOAD_VERSION = 3

    log_entry = models.OneToOneField(LogEntry, on_delete=models.CASCADE)
    hmac = models.CharField(max_length=128)
    is_tampered = models.BooleanField(default=False)
    computed_at = models.DateTimeField(auto_now_add=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "日志完整性记录"
        verbose_name_plural = "日志完整性记录"
        indexes = [
            models.Index(fields=['is_tampered']),
            models.Index(fields=['computed_at']),
        ]

    def __str__(self):
        return f"Integrity for {self.log_entry}"

    @staticmethod
    def _canonical_datetime(value) -> str | None:
        if value is None:
            return None
        if timezone.is_aware(value):
            value = value.astimezone(UTC)
        return value.isoformat(timespec="microseconds")

    @classmethod
    def compose_message(cls, entry: LogEntry) -> str:
        """将 ``LogEntry`` 转换为类型稳定的 v3 JSON 签名载荷。"""
        data = {
            "version": cls.PAYLOAD_VERSION,
            "id": int(entry.id) if entry.id is not None else None,
            "action_time": cls._canonical_datetime(entry.action_time),
            "user_id": int(entry.user_id) if entry.user_id is not None else None,
            "content_type_id": (
                int(entry.content_type_id)
                if entry.content_type_id is not None
                else None
            ),
            "object_id": (
                str(entry.object_id) if entry.object_id is not None else None
            ),
            "object_repr": str(entry.object_repr),
            "action_flag": int(entry.action_flag),
            "change_message": str(entry.change_message),
        }
        return json.dumps(
            data,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def compose_json_v2_message(entry: LogEntry, object_id=None) -> str:
        """生成历史 JSON-v2 载荷，仅用于验证后安全升级旧签名。"""
        data = {
            "id": entry.id,
            "action_time": entry.action_time.isoformat() if entry.action_time else None,
            "user_id": entry.user_id,
            "content_type_id": entry.content_type_id,
            "object_id": entry.object_id if object_id is None else object_id,
            "object_repr": entry.object_repr,
            "action_flag": entry.action_flag,
            "change_message": entry.change_message,
        }
        return json.dumps(data, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def compose_legacy_pipe_message(entry: LogEntry) -> str:
        """生成 v1 管道分隔载荷，仅用于验证后安全升级旧签名。"""
        return (
            f"{entry.id}|{entry.action_time}|{entry.user_id}|"
            f"{entry.content_type_id}|{entry.object_id}|{entry.object_repr}|"
            f"{entry.action_flag}|{entry.change_message}"
        )

    @classmethod
    def calculate_hmac(cls, entry: LogEntry, secret_key: bytes) -> str:
        message = cls.compose_message(entry)
        return sm3_hmac(secret_key, message.encode())

    @classmethod
    def has_valid_hmac(
        cls,
        instance: "SecureLogEntry",
        secret_key: bytes,
    ) -> bool:
        expected = cls.calculate_hmac(instance.log_entry, secret_key)
        return compare_digest(instance.hmac, expected)

    @classmethod
    def compute_from_logentry(cls, entry: LogEntry, secret_key: bytes):
        """为 ``LogEntry`` 补建签名，不覆盖已经存在的审计证据。"""
        hmac_value = cls.calculate_hmac(entry, secret_key)

        obj, created = cls.objects.get_or_create(
            log_entry=entry,
            defaults={
                "hmac": hmac_value,
                "is_tampered": False
            }
        )
        return obj, created

    @classmethod
    def resign(cls, instance: "SecureLogEntry", secret_key: bytes) -> None:
        """以当前规范载荷重签；调用方必须先完成取证或旧签名验证。"""
        instance.hmac = cls.calculate_hmac(instance.log_entry, secret_key)
        instance.is_tampered = False
        instance.last_verified_at = timezone.now()
        instance.save(update_fields=["hmac", "is_tampered", "last_verified_at"])

    @classmethod
    def identify_known_legacy_format(
        cls,
        instance: "SecureLogEntry",
        secret_key: bytes,
    ) -> str | None:
        """识别能由当前数据库内容验证的历史签名格式。"""
        entry = instance.log_entry
        candidates = {
            "legacy-pipe-v1": cls.compose_legacy_pipe_message(entry),
            "json-v2": cls.compose_json_v2_message(entry),
        }
        object_id = entry.object_id
        if isinstance(object_id, str) and object_id.isdecimal():
            candidates["json-v2-int-object-id"] = cls.compose_json_v2_message(
                entry,
                object_id=int(object_id),
            )

        for format_name, message in candidates.items():
            expected = sm3_hmac(secret_key, message.encode())
            if compare_digest(instance.hmac, expected):
                return format_name
        return None

    @classmethod
    def audit_all(cls, secret_key: bytes) -> int:
        """
        审计所有日志信息
        """
        tampered = 0
        for entry in cls.objects.all():
            if cls.audit(entry, secret_key):
                tampered += 1
        return tampered

    @classmethod
    def audit(cls, instance: "SecureLogEntry", secret_key: bytes) -> bool:
        """
            审计单条 SecureLogEntry 实例。
            返回是否被篡改。
        """
        instance.is_tampered = not cls.has_valid_hmac(instance, secret_key)
        instance.last_verified_at = timezone.now()
        instance.save(update_fields=["is_tampered", "last_verified_at"])
        return instance.is_tampered

