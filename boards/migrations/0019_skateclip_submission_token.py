from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0018_alter_music_record_label_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="skateclip",
            name="submission_token",
            field=models.UUIDField(
                blank=True,
                editable=False,
                help_text="用于阻止创建表单因重复点击或网络重试生成重复片段。",
                null=True,
                unique=True,
                verbose_name="创建提交令牌",
            ),
        ),
    ]
