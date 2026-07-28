from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MusicRecordMigrationTests(TransactionTestCase):
    migrate_from = ("boards", "0007_alter_applesnapshot_board_and_more")
    migrate_to = ("boards", "0008_merge_music_snapshot_entry")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        self._create_old_music_data(old_apps)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.new_apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    @staticmethod
    def _create_old_music_data(apps):
        Board = apps.get_model("boards", "Board")
        AppleEntry = apps.get_model("boards", "AppleEntry")
        AppleSnapshot = apps.get_model("boards", "AppleSnapshot")
        SpotifyEntry = apps.get_model("boards", "SpotifyEntry")
        SpotifySnapshot = apps.get_model("boards", "SpotifySnapshot")
        music = Board.objects.create(slug="music", name="Music")

        apple_snapshot = AppleSnapshot.objects.create(
            board=music,
            title="June 2026",
            scope="monthly",
            year=2026,
            month=6,
        )
        AppleEntry.objects.create(
            snapshot=apple_snapshot,
            label="CORE",
            value="Artist",
            value2="Album",
            unit="plays",
            kind="core_artist",
            note="kept note",
            display_order=2,
        )

        spotify_snapshot = SpotifySnapshot.objects.create(
            board=music,
            title="2025 Wrapped",
            scope="yearly",
            year=2025,
        )
        SpotifyEntry.objects.create(
            snapshot=spotify_snapshot,
            label="TOTAL",
            value="32481",
            value2="1200",
            unit="MIN",
            kind="total",
            note="yearly total",
            display_order=1,
        )

    def test_forward_and_backward_migrations_preserve_music_records(self):
        AppleRecord = self.new_apps.get_model("boards", "AppleRecord")
        SpotifyRecord = self.new_apps.get_model("boards", "SpotifyRecord")

        apple = AppleRecord.objects.get()
        spotify = SpotifyRecord.objects.get()
        self.assertEqual(
            (
                apple.title,
                apple.scope,
                apple.year,
                apple.month,
                apple.label,
                apple.value,
                apple.value2,
                apple.unit,
                apple.kind,
                apple.note,
                apple.display_order,
            ),
            (
                "June 2026",
                "monthly",
                2026,
                6,
                "CORE",
                "Artist",
                "Album",
                "plays",
                "core_artist",
                "kept note",
                2,
            ),
        )
        self.assertEqual(spotify.title, "2025 Wrapped")
        self.assertEqual(spotify.value, "32481")
        self.assertEqual(spotify.value2, "1200")
        self.assertEqual(spotify.note, "yearly total")

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        AppleEntry = old_apps.get_model("boards", "AppleEntry")
        SpotifyEntry = old_apps.get_model("boards", "SpotifyEntry")

        restored_apple = AppleEntry.objects.select_related("snapshot").get()
        restored_spotify = SpotifyEntry.objects.select_related("snapshot").get()
        self.assertEqual(restored_apple.snapshot.title, "June 2026")
        self.assertEqual(restored_apple.value2, "Album")
        self.assertEqual(restored_apple.note, "kept note")
        self.assertEqual(restored_spotify.snapshot.title, "2025 Wrapped")
        self.assertEqual(restored_spotify.value, "32481")
