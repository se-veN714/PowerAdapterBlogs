from django.core.management.base import BaseCommand
from django.utils import timezone
from oauth2_provider.models import Grant, RefreshToken
from agent_mcp.models import Connection, WriteReceipt


class Command(BaseCommand):
    help = 'Expire MCP credentials and write receipts while retaining connection/audit history.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        now = timezone.now()
        expired = Connection.objects.filter(expires_at__lte=now)
        if not options['dry_run']:
            for connection in expired:
                RefreshToken.revoke_family(connection.family)
            WriteReceipt.objects.filter(connection__expires_at__lte=now).delete()
            Grant.objects.filter(expires__lte=now).delete()
        self.stdout.write(f'MCP cleanup: {expired.count()} expired connections; history retained.')
