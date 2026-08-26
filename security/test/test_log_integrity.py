from io import StringIO

from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from accounts.models import MyUser
from security.models import SecureLogEntry


class SecureLogEntryIntegrityTest(TestCase):
    def setUp(self):
        self.operator = MyUser.objects.create_user(
            email="integrity@example.com",
            username="integrity-operator",
            password="pass",
            is_active=True,
            is_dashboard_user=True,
        )

    def create_admin_log(self) -> LogEntry:
        entry = LogEntry.objects.log_actions(
            user_id=self.operator.pk,
            queryset=[self.operator],
            action_flag=CHANGE,
            change_message="changed",
            single_object=True,
        )
        SecureLogEntry.compute_from_logentry(
            entry,
            settings.LOG_HMAC_KEY,
            allow_legacy_backfill=True,
        )
        return entry

    def test_admin_log_signature_survives_database_type_conversion(self):
        log_entry = self.create_admin_log()

        self.assertIsInstance(log_entry.object_id, int)
        secure_entry = SecureLogEntry.objects.select_related("log_entry").get(
            log_entry=log_entry,
        )

        self.assertFalse(SecureLogEntry.audit(secure_entry, settings.LOG_HMAC_KEY))

    def test_canonical_payload_normalizes_object_id(self):
        log_entry = self.create_admin_log()
        integer_payload = SecureLogEntry.compose_message(log_entry)

        log_entry.object_id = str(log_entry.object_id)
        string_payload = SecureLogEntry.compose_message(log_entry)

        self.assertEqual(integer_payload, string_payload)

    def test_real_logentry_change_is_still_detected(self):
        log_entry = self.create_admin_log()
        SecureLogEntry.objects.get(log_entry=log_entry)

        LogEntry.objects.filter(pk=log_entry.pk).update(change_message="tampered")
        secure_entry = SecureLogEntry.objects.select_related("log_entry").get(
            log_entry=log_entry,
        )

        self.assertTrue(SecureLogEntry.audit(secure_entry, settings.LOG_HMAC_KEY))

    def test_compute_from_logentry_does_not_overwrite_existing_hmac(self):
        log_entry = self.create_admin_log()
        secure_entry = SecureLogEntry.objects.get(log_entry=log_entry)
        SecureLogEntry.objects.filter(pk=secure_entry.pk).update(hmac="0" * 64)

        result, created = SecureLogEntry.compute_from_logentry(
            log_entry,
            settings.LOG_HMAC_KEY,
            allow_legacy_backfill=True,
        )

        self.assertFalse(created)
        result.refresh_from_db()
        self.assertEqual(result.hmac, "0" * 64)

    def test_legacy_backfill_requires_cutoff_and_acknowledgement(self):
        with self.assertRaises(CommandError):
            call_command("init_log_hmac", stdout=StringIO())

    def test_legacy_backfill_only_creates_missing_rows(self):
        existing_log = self.create_admin_log()
        existing = SecureLogEntry.objects.get(log_entry=existing_log)
        existing_hmac = existing.hmac
        missing_log = LogEntry.objects.create(
            user=self.operator,
            content_type=None,
            object_id="historical",
            object_repr="historical",
            action_flag=CHANGE,
            change_message="historical",
        )
        cutoff = timezone.now().isoformat()

        call_command(
            "init_log_hmac",
            "--before",
            cutoff,
            "--acknowledge-legacy-backfill",
            stdout=StringIO(),
        )

        existing.refresh_from_db()
        self.assertEqual(existing.hmac, existing_hmac)
        self.assertTrue(SecureLogEntry.objects.filter(log_entry=missing_log).exists())
