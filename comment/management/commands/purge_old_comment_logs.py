from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Disabled: core security audit evidence is append-only and has no TTL"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=200)

    def handle(self, *args, **options):
        raise CommandError(
            "Deletion of the core security audit collection is disabled. "
            "Use a separately configured diagnostic-log collection for retention."
        )
