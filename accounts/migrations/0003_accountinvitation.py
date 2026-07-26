import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_add_is_reviewer"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountInvitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_digest", models.CharField(editable=False, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("expires_at", models.DateTimeField(verbose_name="过期时间")),
                ("sent_at", models.DateTimeField(blank=True, null=True, verbose_name="发送时间")),
                ("accepted_at", models.DateTimeField(blank=True, null=True, verbose_name="接受时间")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_account_invitations", to=settings.AUTH_USER_MODEL, verbose_name="邀请人")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="account_invitation", to=settings.AUTH_USER_MODEL, verbose_name="受邀用户")),
            ],
            options={"verbose_name": "账号邀请", "verbose_name_plural": "账号邀请"},
        ),
    ]
