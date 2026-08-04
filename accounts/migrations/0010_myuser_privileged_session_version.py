from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_clientcertificatebinding"),
    ]

    operations = [
        migrations.AddField(
            model_name="myuser",
            name="privileged_session_version",
            field=models.PositiveBigIntegerField(
                default=0,
                editable=False,
                verbose_name="特权会话版本",
            ),
        ),
    ]
