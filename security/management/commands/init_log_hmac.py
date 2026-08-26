from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from security.models import SecureLogEntry


class Command(BaseCommand):
    help = "Backfill only missing frozen PostgreSQL integrity rows before a cutoff"

    def add_arguments(self, parser):
        parser.add_argument(
            "--before",
            help="Required ISO-8601 cutoff for historical LogEntry rows",
        )
        parser.add_argument("--acknowledge-legacy-backfill", action="store_true")

    def handle(self, *args, **options):
        if not options["acknowledge_legacy_backfill"] or not options.get("before"):
            raise CommandError(
                "legacy backfill is frozen; provide --before and "
                "--acknowledge-legacy-backfill"
            )
        cutoff = parse_datetime(options["before"])
        if cutoff is None or cutoff.tzinfo is None:
            raise CommandError(
                "--before must be a timezone-aware ISO-8601 timestamp"
            )

        count = 0
        entries = LogEntry.objects.filter(action_time__lt=cutoff).order_by("pk")
        for entry in entries.iterator(chunk_size=500):
            _integrity, created = SecureLogEntry.compute_from_logentry(
                entry,
                settings.LOG_HMAC_KEY,
                allow_legacy_backfill=True,
            )
            count += int(created)
        self.stdout.write(
            self.style.SUCCESS(f"created {count} missing historical integrity rows")
        )
