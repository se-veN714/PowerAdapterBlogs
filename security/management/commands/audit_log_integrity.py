from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from security.models import (
    AuditCheckpoint,
    AuditOutbox,
    AuditVerificationRun,
    SecureLogEntry,
)
from security.mongo_client import MongoLogger


class Command(BaseCommand):
    help = "Verify Mongo authority, outbox state, or frozen PostgreSQL evidence"

    def add_arguments(self, parser):
        parser.add_argument("--mongo", action="store_true")
        parser.add_argument("--outbox", action="store_true")
        parser.add_argument("--legacy-postgres", action="store_true")
        parser.add_argument("--partition")
        parser.add_argument("--limit", type=int, default=10000)
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument(
            "--checkpoint",
            action="store_true",
            help="Store a signed PostgreSQL checkpoint after a complete valid scan",
        )

    def handle(self, *args, **options):
        selected = sum(
            bool(options[name]) for name in ("outbox", "mongo", "legacy_postgres")
        )
        if selected != 1:
            raise CommandError(
                "select exactly one of --mongo, --outbox, or --legacy-postgres"
            )
        scope = (
            "outbox"
            if options["outbox"]
            else "mongo"
            if options["mongo"]
            else "legacy-postgres"
        )
        run = AuditVerificationRun.objects.create(
            scope=scope,
            partition=options.get("partition") or "",
        )
        try:
            checked_count = self._verify(options)
        except Exception as exc:
            run.status = AuditVerificationRun.Status.FAILED
            run.error_codes = [type(exc).__name__]
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_codes", "completed_at"])
            if isinstance(exc, CommandError):
                raise
            raise CommandError(
                f"audit verification failed error_code={type(exc).__name__}"
            ) from None
        run.status = AuditVerificationRun.Status.PASSED
        run.checked_count = checked_count
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "checked_count", "completed_at"])

    def _verify(self, options):
        if options["outbox"]:
            pending = AuditOutbox.objects.filter(status=AuditOutbox.Status.PENDING).count()
            processing = AuditOutbox.objects.filter(
                status=AuditOutbox.Status.PROCESSING
            ).count()
            dead = AuditOutbox.objects.filter(status=AuditOutbox.Status.DEAD).count()
            self.stdout.write(
                f"outbox pending={pending} processing={processing} dead={dead}"
            )
            if processing or dead:
                raise CommandError("audit outbox requires operator attention")
            return pending + processing + dead

        if options["mongo"]:
            partition = options.get("partition")
            if not partition:
                raise CommandError("--partition is required with --mongo")
            writer = MongoLogger()
            latest = (
                AuditCheckpoint.objects.filter(partition=partition)
                .order_by("-sequence")
                .first()
            )
            checkpoint = None
            if latest:
                if not latest.verify():
                    raise CommandError("stored checkpoint signature is invalid")
                checkpoint = {
                    "partition": latest.partition,
                    "sequence": latest.sequence,
                    "mac": latest.mac,
                }
            result = writer.audit_partition(
                partition,
                limit=options["limit"],
                checkpoint=checkpoint,
            )
            if not result.valid:
                raise CommandError(
                    "Mongo audit verification failed: " + ",".join(result.errors)
                )
            head = writer.get_chain_head(partition)
            if result.last_sequence and not head:
                raise CommandError("Mongo partition head is missing")
            if head and result.last_sequence != head["sequence"]:
                raise CommandError(
                    "scan limit did not reach the partition head; checkpoint not updated"
                )
            if options["checkpoint"] and head:
                AuditCheckpoint.create_signed(**head)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Mongo partition valid events={result.last_sequence}"
                )
            )
            return result.last_sequence

        tampered = SecureLogEntry.audit_all(
            settings.LOG_HMAC_KEY,
            batch_size=max(1, min(options["batch_size"], 5000)),
        )
        if tampered:
            raise CommandError(
                f"PostgreSQL audit verification found {tampered} tampered entries"
            )
        self.stdout.write(
            self.style.SUCCESS(
                "PostgreSQL audit verification completed with no tampered entries"
            )
        )
        return SecureLogEntry.objects.count()
