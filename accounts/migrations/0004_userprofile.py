import accounts.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_accountinvitation"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(blank=True, max_length=64, verbose_name="展示名称")),
                ("bio", models.TextField(blank=True, max_length=500, verbose_name="个人简介")),
                ("avatar", models.ImageField(blank=True, null=True, upload_to=accounts.models.profile_avatar_upload_to, validators=[accounts.models.validate_uploaded_image], verbose_name="头像")),
                ("website", models.URLField(blank=True, verbose_name="个人网站")),
                ("github_url", models.URLField(blank=True, verbose_name="GitHub")),
                ("location", models.CharField(blank=True, max_length=64, verbose_name="所在地")),
                ("is_public", models.BooleanField(default=False, verbose_name="公开作者主页")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL, verbose_name="用户")),
            ],
            options={"verbose_name": "用户资料", "verbose_name_plural": "用户资料"},
        ),
    ]
