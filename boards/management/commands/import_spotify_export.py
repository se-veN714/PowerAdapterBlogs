"""Import derived Spotify Wrapped aggregates without persisting raw history."""

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from boards.models import Board, MusicScope, SpotifyRecord


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CommandError(f"Spotify export file not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise CommandError(f"Invalid Spotify JSON: {path.name}") from exc


def _spotify_url(uri):
    parts = str(uri).split(":")
    if len(parts) == 3 and parts[0] == "spotify" and parts[1] in {"artist", "track"}:
        return f"https://open.spotify.com/{parts[1]}/{parts[2]}"
    return ""


def _minutes(milliseconds):
    return max(0, round(int(milliseconds or 0) / 60_000))


class Command(BaseCommand):
    help = (
        "Import Spotify Wrapped aggregates from a local account export. "
        "Raw streaming history is read only and is never stored."
    )

    def add_arguments(self, parser):
        parser.add_argument("export_dir", type=Path)
        parser.add_argument("--year", type=int, required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        export_dir = options["export_dir"].expanduser().resolve()
        year = options["year"]
        if year < 2000 or year > 2100:
            raise CommandError("--year must be between 2000 and 2100")
        if not export_dir.is_dir():
            raise CommandError("Spotify export directory does not exist")

        wrapped = _read_json(export_dir / f"Wrapped{year}.json")
        library = _read_json(export_dir / "YourLibrary.json")
        history = _read_json(export_dir / "StreamingHistory_music_0.json")

        try:
            board = Board.objects.get(slug="music")
        except Board.DoesNotExist as exc:
            raise CommandError("The music Board must exist before importing") from exc

        artist_names = {
            row.get("uri"): row.get("name", "")
            for row in library.get("artists", [])
            if row.get("uri")
        }
        track_names = {
            row.get("uri"): (row.get("artist", ""), row.get("track", ""))
            for row in library.get("tracks", [])
            if row.get("uri")
        }

        artist_history = defaultdict(lambda: {"plays": 0, "ms": 0})
        for row in history:
            try:
                played_at = datetime.strptime(row.get("endTime", ""), "%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                continue
            if played_at.year != year or not row.get("artistName"):
                continue
            aggregate = artist_history[row["artistName"]]
            aggregate["plays"] += 1
            aggregate["ms"] += max(0, int(row.get("msPlayed") or 0))

        title = f"Spotify Wrapped {year}"
        SpotifyRecord.objects.filter(board=board, title=title).delete()
        records = []

        total_ms = wrapped.get("yearlyMetrics", {}).get("totalMsListened", 0)
        total_minutes = _minutes(total_ms)
        records.append(
            SpotifyRecord(
                board=board,
                title=title,
                scope=MusicScope.YEARLY,
                year=year,
                label="TOTAL MINUTES",
                value=str(total_minutes),
                unit="MIN",
                kind="total",
                minutes=total_minutes,
                display_order=0,
            )
        )

        top_artists = wrapped.get("topArtists", {})
        for rank, uri in enumerate(top_artists.get("topArtistUris", []), start=1):
            name = artist_names.get(uri) or f"Unknown artist {rank}"
            aggregate = artist_history[name]
            records.append(
                SpotifyRecord(
                    board=board,
                    title=title,
                    scope=MusicScope.YEARLY,
                    year=year,
                    label=name,
                    value=str(_minutes(aggregate["ms"])),
                    unit="MIN",
                    kind="top_artist",
                    rank=rank,
                    play_count=aggregate["plays"],
                    minutes=_minutes(aggregate["ms"]),
                    external_url=_spotify_url(uri),
                    display_order=rank,
                )
            )

        top_tracks = wrapped.get("topTracks", {})
        for rank, item in enumerate(top_tracks.get("topTracks", []), start=1):
            uri = item.get("trackUri", "")
            artist, track = track_names.get(uri, ("", f"Unknown track {rank}"))
            records.append(
                SpotifyRecord(
                    board=board,
                    title=title,
                    scope=MusicScope.YEARLY,
                    year=year,
                    label=track,
                    value=artist,
                    kind="top_track",
                    rank=rank,
                    play_count=max(0, int(item.get("count") or 0)),
                    minutes=_minutes(item.get("msPlayed")),
                    external_url=_spotify_url(uri),
                    display_order=rank,
                )
            )

        genres = [
            str(genre).strip()
            for genre in wrapped.get("topGenres", {}).get("topGenres", [])
            if str(genre).strip()
            and not str(genre).startswith("spotify:concept:")
        ]
        for order, genre in enumerate(genres, start=1):
            records.append(
                SpotifyRecord(
                    board=board,
                    title=title,
                    scope=MusicScope.YEARLY,
                    year=year,
                    label=str(genre),
                    value="",
                    kind="tag",
                    display_order=order,
                )
            )

        records.extend(
            [
                SpotifyRecord(
                    board=board,
                    title=title,
                    scope=MusicScope.YEARLY,
                    year=year,
                    label="UNIQUE ARTISTS",
                    value=str(top_artists.get("numUniqueArtists") or 0),
                    kind="unique_artists",
                    display_order=90,
                ),
                SpotifyRecord(
                    board=board,
                    title=title,
                    scope=MusicScope.YEARLY,
                    year=year,
                    label="UNIQUE TRACKS",
                    value=str(top_tracks.get("numUniqueTracks") or 0),
                    kind="unique_tracks",
                    display_order=91,
                ),
            ]
        )

        SpotifyRecord.objects.bulk_create(records)
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(records)} derived Spotify records for {year}; "
                "raw history was not persisted."
            )
        )
