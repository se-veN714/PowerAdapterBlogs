from io import StringIO

from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.core.management import call_command
from django.test import TestCase

from accounts.models import MyUser
from security.models import SecureLogEntry
from security.sec_utils.hmac_utils import sm3_hmac


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
        return LogEntry.objects.log_actions(
            user_id=self.operator.pk,
            queryset=[self.operator],
            action_flag=CHANGE,
            change_message="changed",
            single_object=True,
        )

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
        secure_entry.hmac = "0" * 64
        secure_entry.save(update_fields=["hmac"])

        result, created = SecureLogEntry.compute_from_logentry(
            log_entry,
            settings.LOG_HMAC_KEY,
        )

        self.assertFalse(created)
        self.assertEqual(result.hmac, "0" * 64)

    def test_repair_known_upgrades_json_v2_integer_object_id_signature(self):
        log_entry = self.create_admin_log()
        secure_entry = SecureLogEntry.objects.select_related("log_entry").get(
            log_entry=log_entry,
        )
        legacy_message = SecureLogEntry.compose_json_v2_message(
            secure_entry.log_entry,
            object_id=int(secure_entry.log_entry.object_id),
        )
        secure_entry.hmac = sm3_hmac(
            settings.LOG_HMAC_KEY,
            legacy_message.encode(),
        )
        secure_entry.save(update_fields=["hmac"])

        call_command("init_log_hmac", "--repair-known", stdout=StringIO())

        secure_entry.refresh_from_db()
        self.assertEqual(
            secure_entry.hmac,
            SecureLogEntry.calculate_hmac(
                secure_entry.log_entry,
                settings.LOG_HMAC_KEY,
            ),
        )

    def test_repair_known_upgrades_legacy_pipe_signature(self):
        log_entry = self.create_admin_log()
        secure_entry = SecureLogEntry.objects.select_related("log_entry").get(
            log_entry=log_entry,
        )
        legacy_message = SecureLogEntry.compose_legacy_pipe_message(
            secure_entry.log_entry,
        )
        secure_entry.hmac = sm3_hmac(
            settings.LOG_HMAC_KEY,
            legacy_message.encode(),
        )
        secure_entry.save(update_fields=["hmac"])

        call_command("init_log_hmac", "--repair-known", stdout=StringIO())

        secure_entry.refresh_from_db()
        self.assertTrue(
            SecureLogEntry.has_valid_hmac(secure_entry, settings.LOG_HMAC_KEY),
        )

    def test_repair_known_skips_current_signature_without_warning(self):
        self.create_admin_log()
        output = StringIO()

        call_command("init_log_hmac", "--repair-known", stdout=output)

        self.assertIn("跳过 1 条", output.getvalue())
        self.assertIn("未知/可疑 0 条", output.getvalue())

    def test_repair_known_preserves_unrecognized_signature(self):
        log_entry = self.create_admin_log()
        secure_entry = SecureLogEntry.objects.get(log_entry=log_entry)
        unknown_hmac = "0" * 64
        secure_entry.hmac = unknown_hmac
        secure_entry.save(update_fields=["hmac"])

        call_command("init_log_hmac", "--repair-known", stdout=StringIO())

        secure_entry.refresh_from_db()
        self.assertEqual(secure_entry.hmac, unknown_hmac)
