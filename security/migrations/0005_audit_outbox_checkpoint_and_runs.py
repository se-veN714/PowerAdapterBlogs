import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("security", "0004_alter_securelogentry_options")]

    operations = [
        migrations.CreateModel(
            name="AuditCheckpoint",
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
                ("partition", models.CharField(max_length=128)),
                ("sequence", models.PositiveBigIntegerField()),
                ("mac", models.CharField(max_length=128)),
                ("observed_at", models.DateTimeField(auto_now_add=True)),
                ("key_id", models.CharField(max_length=64)),
                ("checkpoint_hmac", models.CharField(max_length=128)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["partition", "-sequence"],
                        name="security_ac_partiti_30e1_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("partition", "sequence"),
                        name="unique_audit_checkpoint",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="AuditOutbox",
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
                ("event_id", models.UUIDField(editable=False, unique=True)),
                ("event_type", models.CharField(max_length=128)),
                ("partition", models.CharField(max_length=128)),
                ("event", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("delivered", "Delivered"),
                            ("dead", "Dead letter"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                (
                    "next_attempt_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("lock_token", models.UUIDField(blank=True, editable=False, null=True)),
                ("last_error_code", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("delivery_sequence", models.PositiveBigIntegerField(blank=True, null=True)),
                ("delivery_mac", models.CharField(blank=True, default="", max_length=128)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["status", "next_attempt_at"],
                        name="security_ao_status_4d65e1_idx",
                    ),
                    models.Index(
                        fields=["partition", "created_at"],
                        name="security_ao_partiti_7b69_idx",
                    ),
                ]
            },
        ),
        migrations.CreateModel(
            name="AuditVerificationRun",
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
                ("scope", models.CharField(max_length=32)),
                ("partition", models.CharField(blank=True, default="", max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("running", "Running"),
                            ("passed", "Passed"),
                            ("failed", "Failed"),
                        ],
                        default="running",
                        max_length=16,
                    ),
                ),
                ("checked_count", models.PositiveBigIntegerField(default=0)),
                ("error_codes", models.JSONField(blank=True, default=list)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["scope", "status", "-started_at"],
                        name="security_av_scope_84bf_idx",
                    )
                ]
            },
        ),
    ]
