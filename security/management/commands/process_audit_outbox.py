from django.core.management.base import BaseCommand, CommandError

from security.outbox import deliver_outbox_batch


class Command(BaseCommand):
    help = "Deliver a bounded batch of durable audit events to MongoDB"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--max-attempts", type=int, default=12)
        parser.add_argument("--lease-seconds", type=int, default=300)

    def handle(self, *args, **options):
        try:
            result = deliver_outbox_batch(
                limit=options["limit"],
                max_attempts=options["max_attempts"],
                lease_seconds=options["lease_seconds"],
            )
        except Exception as exc:
            raise CommandError(
                f"audit outbox worker failed error_code={type(exc).__name__}"
            ) from None
        self.stdout.write(
            f"delivered={result.delivered} failed={result.failed} "
            f"dead={result.dead} lost_leases={result.lost_leases}"
        )
        if result.dead:
            raise CommandError("one or more audit events reached dead-letter state")
