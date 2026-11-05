from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.agent_auth import _audit_agent_event
from accounts.models import AgentAccessToken, AgentDeviceAuthorization


class Command(BaseCommand):
    help = "清理过期的 Agent 设备授权和访问令牌。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只统计，不删除任何记录。",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        dry_run = options["dry_run"]

        expired_or_revoked_tokens = AgentAccessToken.objects.filter(
            Q(expires_at__lte=now) | Q(revoked_at__isnull=False)
        )
        expired_tokens = list(expired_or_revoked_tokens)
        token_count = len(expired_tokens)
        if not dry_run:
            with transaction.atomic():
                for token in expired_tokens:
                    _audit_agent_event(
                        event_type="agent.token.expired_cleanup",
                        actor=None,
                        target_type="agent_access_token",
                        target_id=token.pk,
                        change={
                            "status": "expired" if token.expires_at <= now else "revoked",
                            "reason_code": "scheduled_cleanup",
                        },
                        source="scheduled_cleanup",
                    )
                AgentAccessToken.objects.filter(
                    pk__in=[token.pk for token in expired_tokens]
                ).delete()

        expired_authorizations = AgentDeviceAuthorization.objects.filter(
            expires_at__lte=now
        ).prefetch_related("tokens")
        authorization_count = 0
        for authorization in expired_authorizations:
            has_live_token = authorization.tokens.filter(
                revoked_at__isnull=True,
                expires_at__gt=now,
            ).exists()
            if has_live_token:
                continue
            authorization_count += 1
            if not dry_run:
                with transaction.atomic():
                    _audit_agent_event(
                        event_type="agent.authorization.expired_cleanup",
                        actor=None,
                        target_type="agent_device_authorization",
                        target_id=authorization.pk,
                        change={"status": authorization.status, "reason_code": "scheduled_cleanup"},
                        source="scheduled_cleanup",
                    )
                    authorization.delete()

        mode = "Would remove" if dry_run else "Removed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} {token_count} expired/revoked tokens and "
                f"{authorization_count} expired device authorizations."
            )
        )
