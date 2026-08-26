from django.core.management.base import BaseCommand, CommandError

from security.mongo_client import MongoLogger


class Command(BaseCommand):
    help = "Create required MongoDB audit indexes"

    def handle(self, *args, **options):
        try:
            MongoLogger().ensure_indexes()
        except Exception as exc:
            raise CommandError(
                f"MongoDB audit index initialization failed error_code={type(exc).__name__}"
            ) from None
        self.stdout.write(self.style.SUCCESS("MongoDB audit indexes are present"))
