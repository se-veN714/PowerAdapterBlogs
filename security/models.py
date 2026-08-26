import json
from datetime import UTC
from hmac import compare_digest

from django.contrib.admin.models import LogEntry
from django.db import models
from django.utils import timezone

from security.audit import AuditKeyring, canonical_json_bytes
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
        permissions = [
            ("view_audit_log", "可查看安全审计日志"),
            ("run_integrity_audit", "可运行日志完整性审计"),
        ]
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
    def compute_from_logentry(
        cls,
        entry: LogEntry,
        secret_key: bytes,
        *,
        allow_legacy_backfill: bool = False,
    ):
        """Create one missing frozen legacy row after explicit acknowledgement."""
        if not allow_legacy_backfill:
            raise RuntimeError(
                "SecureLogEntry creation is frozen after MongoDB authority cutover"
            )
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
        """Historical audit evidence is never re-signed in place."""
        raise RuntimeError("legacy SecureLogEntry re-signing is disabled")

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
    def audit_all(cls, secret_key: bytes, *, batch_size: int = 500) -> int:
        """
        审计所有日志信息
        """
        tampered = 0
        entries = cls.objects.select_related("log_entry").order_by("pk")
        for entry in entries.iterator(chunk_size=batch_size):
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


class AuditOutbox(models.Model):
    """Durable, transactional staging for Mongo-authoritative audit events."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DELIVERED = "delivered", "Delivered"
        DEAD = "dead", "Dead letter"

    event_id = models.UUIDField(unique=True, editable=False)
    event_type = models.CharField(max_length=128)
    partition = models.CharField(max_length=128)
    event = models.JSONField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    locked_at = models.DateTimeField(null=True, blank=True)
    lock_token = models.UUIDField(null=True, blank=True, editable=False)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_sequence = models.PositiveBigIntegerField(null=True, blank=True)
    delivery_mac = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(
                fields=["status", "next_attempt_at"],
                name="security_ao_status_4d65e1_idx",
            ),
            models.Index(
                fields=["partition", "created_at"],
                name="security_ao_partiti_7b69_idx",
            ),
        ]


class AuditCheckpoint(models.Model):
    """Signed Mongo-chain checkpoint awaiting independent WORM anchoring."""

    partition = models.CharField(max_length=128)
    sequence = models.PositiveBigIntegerField()
    mac = models.CharField(max_length=128)
    observed_at = models.DateTimeField(auto_now_add=True)
    key_id = models.CharField(max_length=64)
    checkpoint_hmac = models.CharField(max_length=128)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["partition", "sequence"],
                name="unique_audit_checkpoint",
            ),
        ]
        indexes = [
            models.Index(
                fields=["partition", "-sequence"],
                name="security_ac_partiti_30e1_idx",
            )
        ]

    @classmethod
    def create_signed(cls, *, partition: str, sequence: int, mac: str):
        keyring = AuditKeyring.from_settings("checkpoint")
        payload = {
            "schema_version": 1,
            "purpose": "mongo-chain-checkpoint",
            "partition": partition,
            "sequence": sequence,
            "mac": mac,
            "key_id": keyring.active_key_id,
        }
        signature = sm3_hmac(
            keyring.keys[keyring.active_key_id],
            canonical_json_bytes(payload),
        )
        checkpoint, created = cls.objects.get_or_create(
            partition=partition,
            sequence=sequence,
            defaults={
                "mac": mac,
                "key_id": keyring.active_key_id,
                "checkpoint_hmac": signature,
            },
        )
        if not created and (
            checkpoint.mac != mac
            or checkpoint.key_id != keyring.active_key_id
            or checkpoint.checkpoint_hmac != signature
        ):
            raise ValueError("checkpoint sequence is already bound to different content")
        return checkpoint, created

    def verify(self) -> bool:
        keyring = AuditKeyring.from_settings("checkpoint")
        key = keyring.get(self.key_id)
        if key is None:
            return False
        payload = {
            "schema_version": 1,
            "purpose": "mongo-chain-checkpoint",
            "partition": self.partition,
            "sequence": self.sequence,
            "mac": self.mac,
            "key_id": self.key_id,
        }
        expected = sm3_hmac(key, canonical_json_bytes(payload))
        return compare_digest(self.checkpoint_hmac, expected)


class AuditVerificationRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"

    scope = models.CharField(max_length=32)
    partition = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    checked_count = models.PositiveBigIntegerField(default=0)
    error_codes = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["scope", "status", "-started_at"],
                name="security_av_scope_84bf_idx",
            )
        ]

