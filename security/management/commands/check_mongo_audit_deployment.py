import json

from django.core.management.base import BaseCommand, CommandError

from security.mongo_client import AuditMongoDeploymentError, MongoLogger


class Command(BaseCommand):
    help = "Validate Mongo topology and audit index safety"

    def handle(self, *args, **options):
        try:
            result = MongoLogger().check_deployment()
        except AuditMongoDeploymentError as exc:
            self.stdout.write(
                json.dumps(
                    {"status": "not_ready", "reason_codes": list(exc.reason_codes)},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            raise CommandError("MongoDB audit deployment is not ready") from None
        except Exception as exc:
            self.stdout.write(
                json.dumps(
                    {"status": "unavailable", "error_code": type(exc).__name__[:64]},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            raise CommandError("MongoDB audit deployment check failed") from None
        self.stdout.write(json.dumps(result, separators=(",", ":"), sort_keys=True))
