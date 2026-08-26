from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import MyUser
from PowerAdapterBlogs.base_admin import has_dashboard_access
from security.models import SecureLogEntry


class SecurityOperationsBoundaryTest(TestCase):
    password = "test-password"

    def create_user(self, username):
        return MyUser.objects.create_user(
            email=f"{username}@example.test",
            username=username,
            password=self.password,
            is_active=True,
        )

    def grant(self, user, *codenames):
        user.user_permissions.add(
            *Permission.objects.filter(codename__in=codenames)
        )

    def create_log(self, actor):
        entry = LogEntry.objects.create(
            user=actor,
            content_type=None,
            object_id="1",
            object_repr="test object",
            action_flag=CHANGE,
            change_message="test change",
        )
        SecureLogEntry.compute_from_logentry(
            entry,
            settings.LOG_HMAC_KEY,
            allow_legacy_backfill=True,
        )
        return entry

    def test_site_operator_uses_operations_without_dashboard_access(self):
        operator = self.create_user("site-operator")
        self.grant(operator, "view_audit_log", "run_integrity_audit")
        self.create_log(operator)
        self.client.force_login(operator)

        self.assertFalse(has_dashboard_access(operator))
        self.assertEqual(self.client.get(reverse("cus_admin:index")).status_code, 302)
        response = self.client.get(reverse("operations:security"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "安全运维")
        self.assertContains(response, "未核验")
        self.assertContains(response, "全选本页")
        self.assertContains(response, "清除选择")

    def test_ordinary_user_is_denied(self):
        ordinary = self.create_user("ordinary")
        self.client.force_login(ordinary)

        self.assertEqual(
            self.client.get(reverse("operations:security")).status_code,
            403,
        )

    def test_view_only_operator_cannot_run_audit(self):
        operator = self.create_user("viewer")
        self.grant(operator, "view_audit_log")
        secure_entry = SecureLogEntry.objects.get(
            log_entry=self.create_log(operator)
        )
        self.client.force_login(operator)

        response = self.client.post(
            reverse("operations:security"),
            {"entry_ids": [secure_entry.pk]},
        )
        self.assertEqual(response.status_code, 403)

    def test_authorized_audit_detects_database_tampering(self):
        operator = self.create_user("auditor")
        self.grant(operator, "view_audit_log", "run_integrity_audit")
        log_entry = self.create_log(operator)
        secure_entry = SecureLogEntry.objects.get(log_entry=log_entry)
        LogEntry.objects.filter(pk=log_entry.pk).update(
            change_message="tampered outside model hooks"
        )
        self.client.force_login(operator)

        response = self.client.post(
            reverse("operations:security"),
            {"entry_ids": [secure_entry.pk]},
            follow=True,
        )

        secure_entry.refresh_from_db()
        self.assertTrue(secure_entry.is_tampered)
        self.assertContains(response, "发现 1 条异常")
        self.assertTrue(
            LogEntry.objects.filter(
                user=operator,
                change_message__contains="operations_security checked=1",
            ).exists()
        )
