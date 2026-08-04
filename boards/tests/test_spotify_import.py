import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from boards.models import Board, SpotifyRecord


class SpotifyImportCommandTests(TestCase):
    def setUp(self):
        self.board = Board.objects.create(slug="music", name="Music")

    def test_imports_only_derived_wrapped_records_and_is_idempotent(self):
        with TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir)
            self._write_export(export_dir)

            call_command("import_spotify_export", export_dir, year=2025)
            first_count = SpotifyRecord.objects.count()
            call_command("import_spotify_export", export_dir, year=2025)

        self.assertEqual(SpotifyRecord.objects.count(), first_count)
        total = SpotifyRecord.objects.get(kind="total")
        artist = SpotifyRecord.objects.get(kind="top_artist")
        track = SpotifyRecord.objects.get(kind="top_track")
        self.assertEqual(total.minutes, 120)
        self.assertEqual(artist.label, "Artist A")
        self.assertEqual(artist.play_count, 2)
        self.assertEqual(track.label, "Track A")
        self.assertEqual(track.value, "Artist A")
        self.assertFalse(
            SpotifyRecord.objects.filter(label__contains="2025-03-01 10:00").exists()
        )

    def test_ignores_opaque_spotify_concept_uris(self):
        with TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir)
            self._write_export(export_dir)
            wrapped_path = export_dir / "Wrapped2025.json"
            wrapped = json.loads(wrapped_path.read_text(encoding="utf-8"))
            wrapped["topGenres"]["topGenres"] = [
                "spotify:concept:opaque-id",
                "post-rock",
            ]
            wrapped_path.write_text(json.dumps(wrapped), encoding="utf-8")

            call_command("import_spotify_export", export_dir, year=2025)

        self.assertFalse(
            SpotifyRecord.objects.filter(label__startswith="spotify:concept:").exists()
        )
        self.assertTrue(SpotifyRecord.objects.filter(kind="tag", label="post-rock").exists())

    @staticmethod
    def _write_export(export_dir):
        wrapped = {
            "topArtists": {
                "topArtistUris": ["spotify:artist:artist-a"],
                "numUniqueArtists": 12,
            },
            "topTracks": {
                "topTracks": [
                    {
                        "trackUri": "spotify:track:track-a",
                        "count": 2,
                        "msPlayed": 600_000,
                    }
                ],
                "numUniqueTracks": 34,
            },
            "yearlyMetrics": {"totalMsListened": 7_200_000},
            "topGenres": {"topGenres": ["post-rock"]},
        }
        library = {
            "artists": [{"name": "Artist A", "uri": "spotify:artist:artist-a"}],
            "tracks": [
                {
                    "artist": "Artist A",
                    "track": "Track A",
                    "uri": "spotify:track:track-a",
                }
            ],
        }
        history = [
            {
                "endTime": "2025-03-01 10:00",
                "artistName": "Artist A",
                "trackName": "Track A",
                "msPlayed": 300_000,
            },
            {
                "endTime": "2025-03-02 10:00",
                "artistName": "Artist A",
                "trackName": "Track A",
                "msPlayed": 300_000,
            },
        ]
        (export_dir / "Wrapped2025.json").write_text(
            json.dumps(wrapped),
            encoding="utf-8",
        )
        (export_dir / "YourLibrary.json").write_text(
            json.dumps(library),
            encoding="utf-8",
        )
        (export_dir / "StreamingHistory_music_0.json").write_text(
            json.dumps(history),
            encoding="utf-8",
        )
