from pathlib import Path
import uuid

from django.conf import settings
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
import logging

from PowerAdapterBlogs.image_validation import validate_uploaded_image

from .thread_local import get_current_user

logger = logging.getLogger(__name__)

# 敏感权限字段：非 superuser 禁止修改
SENSITIVE_FIELDS = {"is_superuser", "is_staff", "is_dashboard_user", "is_reviewer"}


def profile_avatar_upload_to(_instance, filename):
    """使用服务端随机文件名保存头像，避免信任客户端路径。"""
    extension = Path(filename).suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        extension = ".upload"
    return f"profile-avatars/{uuid.uuid4().hex}{extension}"


# Create your models here.
class UserManager(BaseUserManager):
    def create_user(self, email, username, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_dashboard_user", True)
        extra_fields.setdefault("is_reviewer", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, username, password, **extra_fields)


class MyUser(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=30, unique=True)
    email = models.EmailField(unique=True)
    cert_sn = models.CharField(max_length=128, blank=True, null=True, unique=True)
    cert_subject_dn = models.TextField(blank=True, null=True)
    is_cert_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    # 权限字段（四旗模型 + 审核角色）
    is_active = models.BooleanField(default=False, verbose_name="账号启用")
    is_staff = models.BooleanField(default=False, verbose_name="超级管理员入口")
    is_dashboard_user = models.BooleanField(default=False, verbose_name="仪表盘入口")
    is_reviewer = models.BooleanField(default=False, verbose_name="内容审核权限")

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        permissions = [
            ("manage_user_accounts", "可管理用户账号"),
        ]

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        """
        模型层纵深防御：非 superuser 调用 save() 时，回滚敏感权限字段。

        防御场景：
        - Admin UI has_change_permission 被绕过
        - 通过 ORM/API/Shell 直接修改敏感字段
        - 第三方包的意外提权

        注意：groups 和 user_permissions（M2M）由 admin.save_related() 守卫。
        """
        requesting_user = get_current_user()

        if requesting_user and not requesting_user.is_superuser and self.pk:
            # 拉取旧值（仅敏感字段，减少查询开销）
            try:
                old = MyUser.objects.only(*SENSITIVE_FIELDS).get(pk=self.pk)
            except MyUser.DoesNotExist:
                old = None

            if old is not None:
                for field in SENSITIVE_FIELDS:
                    new_val = getattr(self, field)
                    old_val = getattr(old, field)
                    if new_val != old_val:
                        # 回滚：非 superuser 不得修改敏感字段
                        setattr(self, field, old_val)
                        logger.warning(
                            f"[SECURITY] 提权尝试被阻止: "
                            f"operator={requesting_user.username}(id={requesting_user.id}) "
                            f"target={self.username}(id={self.pk}) "
                            f"field={field} old={old_val} new={new_val}"
                        )

        super().save(*args, **kwargs)


class AccountInvitation(models.Model):
    """管理员发放账号后，由受邀用户完成密码设置和激活。"""

    user = models.OneToOneField(
        MyUser,
        on_delete=models.CASCADE,
        related_name="account_invitation",
        verbose_name="受邀用户",
    )
    created_by = models.ForeignKey(
        MyUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_account_invitations",
        verbose_name="邀请人",
    )
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    expires_at = models.DateTimeField(verbose_name="过期时间")
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="发送时间")
    accepted_at = models.DateTimeField(null=True, blank=True, verbose_name="接受时间")

    class Meta:
        verbose_name = "账号邀请"
        verbose_name_plural = "账号邀请"

    @property
    def is_pending(self):
        from django.utils import timezone

        return self.accepted_at is None and self.expires_at > timezone.now()

    def __str__(self):
        return f"{self.user.username} 的账号邀请"


class UserProfile(models.Model):
    """用户主动维护的公开作者资料；认证和权限字段仍留在 MyUser。"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="用户",
    )
    display_name = models.CharField(max_length=64, blank=True, verbose_name="展示名称")
    bio = models.TextField(max_length=500, blank=True, verbose_name="个人简介")
    avatar = models.ImageField(
        upload_to=profile_avatar_upload_to,
        validators=(validate_uploaded_image,),
        blank=True,
        null=True,
        verbose_name="头像",
    )
    website = models.URLField(blank=True, verbose_name="个人网站")
    github_url = models.URLField(blank=True, verbose_name="GitHub")
    location = models.CharField(max_length=64, blank=True, verbose_name="所在地")
    is_public = models.BooleanField(default=False, verbose_name="公开作者主页")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "用户资料"
        verbose_name_plural = "用户资料"

    @property
    def public_name(self):
        return self.display_name.strip() or self.user.username

    def get_absolute_url(self):
        return reverse(
            "accounts:profile-detail", kwargs={"username": self.user.username}
        )

    def __str__(self):
        return f"{self.user.username} 的资料"


class MfaTotpDevice(models.Model):
    """A user's encrypted TOTP seed and its lifecycle metadata.

    The plaintext seed and provisioning URI must never be persisted here.
    Encryption and decryption stay behind ``accounts.mfa_crypto``.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "待确认"
        ACTIVE = "active", "已启用"
        REVOKED = "revoked", "已撤销"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa_totp_device",
        verbose_name="用户",
    )
    status = models.CharField(
        max_length=8,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="状态",
    )
    secret_ciphertext = models.BinaryField(editable=False, verbose_name="种子密文")
    secret_nonce = models.BinaryField(editable=False, verbose_name="加密随机数")
    key_id = models.CharField(max_length=32, editable=False, verbose_name="密钥版本")
    binding_expires_at = models.DateTimeField(verbose_name="绑定过期时间")
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="确认时间",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="撤销时间",
    )
    last_accepted_step = models.BigIntegerField(
        null=True,
        blank=True,
        editable=False,
        verbose_name="最后接受的时间步",
    )
    auth_version = models.PositiveIntegerField(
        default=1,
        editable=False,
        verbose_name="认证版本",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "TOTP 设备"
        verbose_name_plural = "TOTP 设备"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="pending",
                        confirmed_at__isnull=True,
                        revoked_at__isnull=True,
                    )
                    | models.Q(
                        status="active",
                        confirmed_at__isnull=False,
                        revoked_at__isnull=True,
                    )
                    | models.Q(status="revoked", revoked_at__isnull=False)
                ),
                name="accounts_mfa_totp_status_dates_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(auth_version__gte=1),
                name="accounts_mfa_totp_auth_version_gte_1",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(last_accepted_step__isnull=True)
                    | models.Q(last_accepted_step__gte=0)
                ),
                name="accounts_mfa_totp_step_nonnegative",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        nonce = bytes(self.secret_nonce or b"")
        ciphertext = bytes(self.secret_ciphertext or b"")
        if len(nonce) != 12:
            errors["secret_nonce"] = "TOTP 加密随机数必须为 12 字节。"
        # AES-GCM appends a 16-byte authentication tag to a non-empty seed.
        if len(ciphertext) < 17:
            errors["secret_ciphertext"] = "TOTP 种子密文格式无效。"
        if not self.key_id or not all(
            character.isascii() and (character.isalnum() or character in "._-")
            for character in self.key_id
        ):
            errors["key_id"] = "TOTP 密钥版本标识无效。"
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.user.username} / {self.status} / {self.pk}"
