from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("Blogs", "0007_postworkflowevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="postrevision",
            name="diff_algorithm",
            field=models.CharField(
                blank=True,
                default="",
                max_length=48,
                verbose_name="差异算法版本",
            ),
        ),
        migrations.AddField(
            model_name="postrevision",
            name="diff_stats",
            field=models.JSONField(
                blank=True,
                default=dict,
                verbose_name="差异统计",
            ),
        ),
        migrations.AddField(
            model_name="postrevision",
            name="diff_structured",
            field=models.JSONField(
                blank=True,
                null=True,
                verbose_name="结构化差异",
            ),
        ),
    ]
