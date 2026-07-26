import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("Blogs", "0006_add_post_status_and_permissions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PostWorkflowEvent",
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
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("submitted", "提交审核"),
                            ("approved", "审核通过并发布"),
                            ("rejected", "审核驳回"),
                            ("unpublished", "文章下架"),
                            ("returned_to_draft", "编辑后退回草稿"),
                            ("status_changed", "状态变更"),
                        ],
                        max_length=32,
                        verbose_name="事件类型",
                    ),
                ),
                (
                    "from_status",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (0, "删除"),
                            (1, "已发布"),
                            (2, "草稿"),
                            (3, "审核中"),
                        ],
                        verbose_name="原状态",
                    ),
                ),
                (
                    "to_status",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (0, "删除"),
                            (1, "已发布"),
                            (2, "草稿"),
                            (3, "审核中"),
                        ],
                        verbose_name="新状态",
                    ),
                ),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="说明")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="发生时间")),
                (
                    "actor",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="post_workflow_events",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="操作人",
                    ),
                ),
                (
                    "post",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workflow_events",
                        to="Blogs.post",
                        verbose_name="文章",
                    ),
                ),
                (
                    "revision",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="workflow_events",
                        to="Blogs.postrevision",
                        verbose_name="关联修订",
                    ),
                ),
            ],
            options={
                "verbose_name": "文章工作流事件",
                "verbose_name_plural": "文章工作流事件",
                "ordering": ["-created_at", "-pk"],
                "indexes": [
                    models.Index(
                        fields=["post", "-created_at"],
                        name="blog_workflow_post_time",
                    ),
                ],
            },
        ),
    ]
