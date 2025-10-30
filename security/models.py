# Create your models here.
from django.contrib.admin.models import LogEntry
from django.db import models
from django.utils import timezone
from django.conf import settings

from comment.models import Comment
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
        """
        处理LogEntry模型的字段并整合为字符串
        :param entry: LogEntry 实例
        :return: 日志信息
        """
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


class CommentEventLog(models.Model):
    """合规模块：记录用户动作 + 取证链（不少于6个月）"""

    class UserAction(models.IntegerChoices):
        CREATE = 1, "创建评论"
        UPDATE = 2, "编辑评论"
        DELETE = 3, "删除评论"
        MODERATE = 0, "审核操作"  # 管理员动作

    comment = models.ForeignKey(Comment, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    action = models.CharField(max_length=16, choices=UserAction.choices, db_index=True)
    action_at = models.DateTimeField(default=timezone.now, db_index=True)

    # 关键合规要素
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.TextField()  # 上线后建议换成加密字段
    referrer = models.TextField(null=True, blank=True)
    url_path = models.CharField(max_length=256, null=True, blank=True)

    # 客户端指纹（可选）：例如 UA+IP+Accept-Language 的哈希，用于同源识别但不直接存敏感组合
    client_fingerprint = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    # 快照与完整性
    comment_snapshot = models.JSONField()  # 保存当时的评论关键快照（id、内容、状态、时间、展示名）
    record_hash = models.CharField(max_length=64, editable=False, db_index=True)  # 当前记录的 HMAC
    prev_record_hash = models.CharField(max_length=64, null=True, blank=True)  # 上一条日志的 HMAC（构造链）
    chain_head_key = models.CharField(max_length=64, db_index=True)  # 以 comment_id 或“全局链”作链头分片，提高校验性能

    # 数据最小化：可选掩码字段（如果要对外展示）
    masked_ip = models.CharField(max_length=64, null=True, blank=True, editable=False)

    def save(self, *args, **kwargs):
        # 生成链头：以评论ID或“GLOBAL”聚合系统级操作
        self.chain_head_key = str(self.comment_id or "GLOBAL")
        if self.ip_address and ":" not in self.ip_address:  # IPv4 简单掩码展示
            parts = self.ip_address.split(".")
            if len(parts) == 4:
                self.masked_ip = ".".join(parts[:3] + ["*"])

        # 取上一条日志哈希（同一链头）
        prev = CommentEventLog.objects.filter(chain_head_key=self.chain_head_key).order_by("-id").first()
        self.prev_record_hash = prev.record_hash if prev else None

        payload = {
            "comment_id": self.comment_id,
            "action": self.action,
            "action_at": self.action_at.isoformat(),
            "ip_address": self.ip_address,
            "user_agent_hash": self.user_agent,  # HMAC 签名用原文，payload里用 hash 减少扩散
            "referrer": self.referrer, # 跳转的来源页面
            "url_path": self.url_path,
            "client_fingerprint": self.client_fingerprint,
            "comment_snapshot": self.comment_snapshot,
            "prev_record_hash": self.prev_record_hash,
            "chain_head_key": self.chain_head_key,
        }
        payload_str = f"{payload}".encode()
        self.record_hash = sm3_hmac(settings.LOG_HMAC_KEY, payload_str)
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=["action_at"]),
            models.Index(fields=["chain_head_key", "id"]),
        ]
        verbose_name = "评论事件日志"
        verbose_name_plural = "评论事件日志"
