# Generated by Django 5.1.5 on 2025-02-10 19:50

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("Blogs", "0002_alter_category_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Comment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("content", models.TextField(max_length=2000, verbose_name="内容")),
                ("nickname", models.CharField(max_length=50, verbose_name="昵称")),
                ("email", models.EmailField(max_length=254, verbose_name="邮箱")),
                (
                    "status",
                    models.PositiveIntegerField(
                        choices=[(1, "正常"), (0, "删除")],
                        default=1,
                        verbose_name="状态",
                    ),
                ),
                (
                    "created_time",
                    models.DateTimeField(auto_now_add=True, verbose_name="创建时间"),
                ),
                (
                    "target",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="Blogs.post",
                        verbose_name="评论目标",
                    ),
                ),
            ],
            options={
                "verbose_name": "评论",
                "verbose_name_plural": "评论",
            },
        ),
    ]
