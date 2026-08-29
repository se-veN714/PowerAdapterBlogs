import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from boards.models import AppleRecord, Board, MusicArtist, SpotifyRecord
from boards.music_record_import import load_music_payload


class SpotifyRecordsImportCommandTests(TestCase):
    def setUp(self):
        self.board = Board.objects.create(slug="music", name="Music")

    def test_import_is_idempotent_updates_and_removes_same_key_duplicates(self):
        SpotifyRecord.objects.create(
            board=self.board,
            title="Old",
            scope="yearly",
            year=2025,
            kind="top_artist",
            label="Duplicate A",
            value="1",
            rank=1,
        )
        SpotifyRecord.objects.create(
            board=self.board,
            title="Old duplicate",
            scope="yearly",
            year=2025,
            kind="top_artist",
            label="Duplicate B",
            value="2",
            rank=1,
        )
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "spotify.json"
            source.write_text(json.dumps(self._payload()), encoding="utf-8")
            call_command("import_spotify_records", source)
            call_command("import_spotify_records", source)

        records = SpotifyRecord.objects.filter(year=2025, kind="top_artist", rank=1)
        self.assertEqual(records.count(), 1)
        self.assertEqual(records.get().label, "Artist A")
        self.assertEqual(records.get().minutes, 120)
        self.assertEqual(records.get().artist.name, "Artist A")
        self.assertEqual(MusicArtist.objects.count(), 1)

    def test_dry_run_rolls_back_changes(self):
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "spotify.json"
            source.write_text(json.dumps(self._payload()), encoding="utf-8")
            call_command("import_spotify_records", source, dry_run=True)

        self.assertFalse(SpotifyRecord.objects.exists())

    @staticmethod
    def _payload():
        return {
            "schema_version": 1,
            "provider": "spotify",
            "records": [
                {
                    "title": "Spotify Wrapped 2025",
                    "scope": "yearly",
                    "year": 2025,
                    "month": None,
                    "kind": "top_artist",
                    "label": "Artist A",
                    "artist_name": "Artist A",
                    "value": "120",
                    "unit": "MIN",
                    "rank": 1,
                    "play_count": 20,
                    "minutes": 120,
                    "display_order": 1,
                }
            ],
        }


class AppleRecordsImportCommandTests(TestCase):
    def setUp(self):
        self.board = Board.objects.create(slug="music", name="Music")

    def test_import_uses_shared_artist_identity_and_updates_in_place(self):
        artist = MusicArtist.objects.create(
            board=self.board,
            name="Kashiwa Daisuke",
        )
        payload = {
            "schema_version": 1,
            "provider": "apple",
            "records": [
                {
                    "title": "Apple Music 2026.07",
                    "scope": "monthly",
                    "year": 2026,
                    "month": 7,
                    "kind": "top_artist",
                    "label": "Kashiwa Daisuke",
                    "artist_name": "  KASHIWA Daisuke ",
                    "value": "1181",
                    "unit": "MIN",
                    "rank": 1,
                    "minutes": 1181,
                    "external_url": "https://music.apple.com/example",
                    "display_order": 1,
                }
            ],
        }
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "apple.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            call_command("import_apple_music_records", source)
            payload["records"][0]["minutes"] = 1200
            payload["records"][0]["value"] = "1200"
            source.write_text(json.dumps(payload), encoding="utf-8")
            call_command("import_apple_music_records", source)

        record = AppleRecord.objects.get()
        artist.refresh_from_db()
        self.assertEqual(record.artist, artist)
        self.assertEqual(record.minutes, 1200)
        self.assertEqual(artist.apple_music_url, "https://music.apple.com/example")
        self.assertEqual(MusicArtist.objects.count(), 1)

    def test_packaged_payload_labels_fit_the_model_contract(self):
        source = Path(__file__).resolve().parents[1] / "data" / "apple_music_records.json"
        records = load_music_payload(source, "apple")
        max_length = AppleRecord._meta.get_field("label").max_length

        self.assertTrue(records)
        self.assertLessEqual(max(len(str(record["label"])) for record in records), max_length)

    def test_undeclared_artist_does_not_clear_manual_association(self):
        artist = MusicArtist.objects.create(board=self.board, name="Manual Artist")
        record = AppleRecord.objects.create(
            board=self.board,
            artist=artist,
            title="Manual",
            scope="monthly",
            year=2026,
            month=7,
            kind="gravity",
            label="Gravity",
            value="Near",
        )
        payload = {
            "schema_version": 1,
            "provider": "apple",
            "records": [
                {
                    "title": "Manual updated",
                    "scope": "monthly",
                    "year": 2026,
                    "month": 7,
                    "kind": "gravity",
                    "label": "Gravity",
                    "value": "Closer",
                }
            ],
        }
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "apple.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            call_command("import_apple_music_records", source)

        record.refresh_from_db()
        self.assertEqual(record.artist, artist)
        self.assertEqual(record.value, "Closer")
