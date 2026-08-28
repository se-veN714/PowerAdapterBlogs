"""Import deployment-safe Spotify aggregates from normalized JSON."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from boards.models import Board
from boards.music_record_import import import_music_records, load_music_payload


DEFAULT_SOURCE = Path(__file__).resolve().parents[2] / "data" / "spotify_records.json"


class Command(BaseCommand):
    help = "Import normalized Spotify aggregates idempotently for deployment."

    def add_arguments(self, parser):
        parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        source = options["source"].expanduser().resolve()
        try:
            board = Board.objects.get(slug="music")
        except Board.DoesNotExist as exc:
            raise CommandError("The music Board must exist before importing") from exc
        result = import_music_records(
            board=board,
            provider="spotify",
            records=load_music_payload(source, "spotify"),
        )
        if options["dry_run"]:
            transaction.set_rollback(True)
        mode = "DRY RUN" if options["dry_run"] else "IMPORTED"
        self.stdout.write(self.style.SUCCESS(
            f"{mode}: {result['created']} created, {result['updated']} updated, "
            f"{result['deduplicated']} duplicates removed from {source.name}."
        ))
