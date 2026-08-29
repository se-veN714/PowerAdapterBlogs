import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("config", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContentReport",
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
                    "reference",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                        verbose_name="受理编号",
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("illegal_harmful", "违法或不良信息"),
                            ("infringement", "侵权"),
                            ("privacy", "隐私或个人信息"),
                            ("spam", "垃圾信息或骚扰"),
                            ("appeal", "内容处置申诉"),
                            ("other", "其他"),
                        ],
                        max_length=32,
                        verbose_name="问题类型",
                    ),
                ),
                (
                    "target_path",
                    models.CharField(
                        blank=True,
                        max_length=500,
                        verbose_name="本站位置",
                    ),
                ),
                (
                    "description",
                    models.TextField(max_length=2000, verbose_name="问题说明"),
                ),
                (
                    "contact_email",
                    models.EmailField(
                        blank=True,
                        max_length=254,
                        verbose_name="联系邮箱",
                    ),
                ),
                (
                    "source_ip_digest",
                    models.CharField(
                        editable=False,
                        max_length=64,
                        verbose_name="来源地址摘要",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "待受理"),
                            ("reviewing", "处理中"),
                            ("resolved", "已处理"),
                            ("rejected", "不予处理"),
                        ],
                        default="pending",
                        max_length=16,
                        verbose_name="处理状态",
                    ),
                ),
                ("internal_note", models.TextField(blank=True, verbose_name="内部处理记录")),
                ("public_response", models.TextField(blank=True, verbose_name="公开处理反馈")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="提交时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                (
                    "resolved_at",
                    models.DateTimeField(
                        blank=True,
                        editable=False,
                        null=True,
                        verbose_name="处理完成时间",
                    ),
                ),
                (
                    "submitted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="submitted_content_reports",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="提交账号",
                    ),
                ),
            ],
            options={
                "verbose_name": "投诉举报",
                "verbose_name_plural": "投诉举报",
                "ordering": ("-created_at",),
            },
        )
    ]
