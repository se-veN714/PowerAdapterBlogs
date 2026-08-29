import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_remove_myuser_is_reviewer"),
    ]

    operations = [
        migrations.AddField(
            model_name="myuser",
            name="identity_verification_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("mobile_phone", "移动电话号码"),
                    ("identity_document", "身份证件"),
                    ("social_credit_code", "统一社会信用代码"),
                ],
                help_text="只记录核验方式，不在本站保存手机号或证件号码。",
                max_length=24,
                verbose_name="真实身份核验方式",
            ),
        ),
        migrations.AddField(
            model_name="myuser",
            name="identity_verified_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="真实身份核验时间",
            ),
        ),
        migrations.AddField(
            model_name="myuser",
            name="identity_verified_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="identity_verifications_performed",
                to=settings.AUTH_USER_MODEL,
                verbose_name="核验操作人",
            ),
        ),
    ]
