from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
import logging

from .thread_local import get_current_user

logger = logging.getLogger(__name__)

# 敏感权限字段：非 superuser 禁止修改
SENSITIVE_FIELDS = {'is_superuser', 'is_staff', 'is_dashboard_user', 'is_reviewer'}


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

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

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
