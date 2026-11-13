from django.core.management.base import BaseCommand
from django.utils import timezone
from oauth2_provider.models import Grant, RefreshToken
from agent_mcp.models import Connection, WriteReceipt, MarkdownUpload
from agent_mcp.uploads import ACTIVE, cleanup_task


class Command(BaseCommand):
    help = 'Expire MCP credentials and write receipts while retaining connection/audit history.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        now = timezone.now()
        expired = Connection.objects.filter(expires_at__lte=now)
        purged = 0
        if not options['dry_run']:
            for upload_id in MarkdownUpload.objects.filter(state__in=ACTIVE).values_list('pk', flat=True).iterator():
                purged += int(cleanup_task(str(upload_id)))
            for connection in expired:
                RefreshToken.revoke_family(connection.family)
            WriteReceipt.objects.filter(connection__expires_at__lte=now).delete()
            Grant.objects.filter(expires__lte=now).delete()
        self.stdout.write(f'MCP cleanup: {expired.count()} expired connections; history retained.')
        self.stdout.write(f'MCP upload cleanup: {purged} tasks purged; history retained.')
