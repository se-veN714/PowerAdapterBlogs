import json

from django.core.management.base import BaseCommand, CommandError

from security.outbox import reconcile_delivered_outbox


class Command(BaseCommand):
    help = "Reconcile delivered outbox receipts with Mongo-authoritative evidence"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        try:
            result = reconcile_delivered_outbox(limit=options["limit"])
        except Exception as exc:
            raise CommandError(
                f"audit reconciliation unavailable error_code={type(exc).__name__}"
            ) from None
        payload = {
            "healthy": result.healthy,
            "checked": result.checked,
            "missing": result.missing,
            "invalid": result.invalid,
            "receipt_mismatch": result.receipt_mismatch,
        }
        self.stdout.write(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        if not result.healthy:
            raise CommandError("audit reconciliation found inconsistent evidence")
