# Create your models here.
from django.contrib.admin.models import LogEntry
from django.db import models
from django.utils import timezone

from security.sec_utils.hmac_utils import sm3_hmac


class SecureLogEntry(models.Model):
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
    def compose_message(entry: LogEntry) -> str:
        return f"{entry.id}|{entry.action_time}|{entry.user_id}|{entry.content_type_id}|{entry.object_id}|{entry.object_repr}|{entry.action_flag}|{entry.change_message}"

    @classmethod
    def calculate_hmac(cls, entry: LogEntry, secret_key: bytes) -> str:
        message = cls.compose_message(entry)
        return sm3_hmac(secret_key, message.encode())

    @classmethod
    def compute_from_logentry(cls, entry: LogEntry, secret_key: bytes):
        """
        从 LogEntry 创建或更新对应的 SecureLogEntry。
        """
        hmac_value = cls.calculate_hmac(entry, secret_key)

        obj, created = cls.objects.update_or_create(
            log_entry=entry,
            defaults={
                "hmac": hmac_value,
                "is_tampered": False
            }
        )
        return obj, created

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
        expected = cls.calculate_hmac(instance.log_entry, secret_key)
        instance.is_tampered = (instance.hmac != expected)
        instance.last_verified_at = timezone.now()
        instance.save(update_fields=["is_tampered", "last_verified_at"])
        return instance.is_tampered
