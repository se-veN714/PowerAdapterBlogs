from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("Blogs", "0008_postrevision_structured_diff"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="post",
            index=models.Index(
                fields=["status", "-created_time", "-id"],
                name="post_status_created_idx",
            ),
        ),
    ]
