import json

from django.core.management.base import BaseCommand, CommandError

from security.models import AuditCheckpoint


class Command(BaseCommand):
    help = "Export the latest signed checkpoint for external immutable storage"

    def add_arguments(self, parser):
        parser.add_argument("--partition", required=True)

    def handle(self, *args, **options):
        checkpoint = (
            AuditCheckpoint.objects.filter(partition=options["partition"])
            .order_by("-sequence")
            .first()
        )
        if checkpoint is None:
            raise CommandError("no checkpoint exists for this partition")
        if not checkpoint.verify():
            raise CommandError("checkpoint signature is invalid")
        self.stdout.write(
            json.dumps(
                {
                    "partition": checkpoint.partition,
                    "sequence": checkpoint.sequence,
                    "mac": checkpoint.mac,
                    "observed_at": checkpoint.observed_at.isoformat(),
                    "key_id": checkpoint.key_id,
                    "checkpoint_hmac": checkpoint.checkpoint_hmac,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
