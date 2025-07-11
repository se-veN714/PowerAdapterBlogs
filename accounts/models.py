from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


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
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, username, password, **extra_fields)


class MyUser(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=30, unique=True)
    email = models.EmailField(unique=True)
    cert_sn = models.CharField(max_length=128, blank=True, null=True, unique=True)
    cert_subject_dn = models.TextField(blank=True, null=True)
    is_cert_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    # 权限字段
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)  # ✅ ← 必须添加这个字段
    is_dashboard_user = models.BooleanField(default=False)  # 自定义后台登录权限

    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    def __str__(self):
        return self.username
