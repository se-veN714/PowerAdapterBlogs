import json

from django.core.management.base import BaseCommand, CommandError

from security.outbox import collect_outbox_health


class Command(BaseCommand):
    help = "Report payload-free audit outbox health"

    def add_arguments(self, parser):
        parser.add_argument("--max-pending", type=int, default=1000)
        parser.add_argument("--max-oldest-pending-seconds", type=int, default=300)
        parser.add_argument("--lease-seconds", type=int, default=300)

    def handle(self, *args, **options):
        health = collect_outbox_health(
            max_pending=options["max_pending"],
            max_oldest_pending_seconds=options["max_oldest_pending_seconds"],
            lease_seconds=options["lease_seconds"],
        )
        self.stdout.write(json.dumps(health.as_dict(), separators=(",", ":"), sort_keys=True))
        if not health.healthy:
            raise CommandError("audit outbox health thresholds exceeded")
