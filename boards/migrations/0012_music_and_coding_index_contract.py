import boards.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0011_boardmembershipevent_and_membership_updated_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="applerecord",
            name="cover",
            field=models.ImageField(
                blank=True,
                upload_to=boards.models.board_content_cover_upload_to,
                validators=[boards.models.validate_uploaded_image],
                verbose_name="封面",
            ),
        ),
        migrations.AddField(
            model_name="applerecord",
            name="external_url",
            field=models.URLField(blank=True, verbose_name="外部链接"),
        ),
        migrations.AddField(
            model_name="applerecord",
            name="minutes",
            field=models.PositiveBigIntegerField(
                blank=True,
                null=True,
                verbose_name="收听分钟",
            ),
        ),
        migrations.AddField(
            model_name="applerecord",
            name="play_count",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name="播放次数",
            ),
        ),
        migrations.AddField(
            model_name="applerecord",
            name="rank",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                verbose_name="排名",
            ),
        ),
        migrations.AddField(
            model_name="spotifyrecord",
            name="cover",
            field=models.ImageField(
                blank=True,
                upload_to=boards.models.board_content_cover_upload_to,
                validators=[boards.models.validate_uploaded_image],
                verbose_name="封面",
            ),
        ),
        migrations.AddField(
            model_name="spotifyrecord",
            name="external_url",
            field=models.URLField(blank=True, verbose_name="外部链接"),
        ),
        migrations.AddField(
            model_name="spotifyrecord",
            name="minutes",
            field=models.PositiveBigIntegerField(
                blank=True,
                null=True,
                verbose_name="收听分钟",
            ),
        ),
        migrations.AddField(
            model_name="spotifyrecord",
            name="play_count",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name="播放次数",
            ),
        ),
        migrations.AddField(
            model_name="spotifyrecord",
            name="rank",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                verbose_name="排名",
            ),
        ),
        migrations.AddField(
            model_name="codingproject",
            name="cover",
            field=models.ImageField(
                blank=True,
                upload_to=boards.models.board_content_cover_upload_to,
                validators=[boards.models.validate_uploaded_image],
                verbose_name="封面",
            ),
        ),
        migrations.AddField(
            model_name="codingproject",
            name="demo_url",
            field=models.URLField(blank=True, verbose_name="演示链接"),
        ),
        migrations.AddField(
            model_name="codingproject",
            name="is_featured",
            field=models.BooleanField(default=False, verbose_name="精选"),
        ),
        migrations.AddField(
            model_name="codingproject",
            name="project_type",
            field=models.CharField(
                choices=[
                    ("github", "GitHub 项目"),
                    ("local_tool", "本地浏览器工具"),
                    ("external", "外部项目"),
                ],
                default="github",
                max_length=16,
                verbose_name="项目类型",
            ),
        ),
        migrations.AddField(
            model_name="codingproject",
            name="repository_url",
            field=models.URLField(blank=True, verbose_name="仓库链接"),
        ),
        migrations.AlterField(
            model_name="codingproject",
            name="url",
            field=models.URLField(
                blank=True,
                help_text="历史数据兼容字段；新数据优先填写仓库链接或演示链接。",
                verbose_name="兼容主链接",
            ),
        ),
    ]
