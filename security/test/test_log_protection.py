from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from accounts.models import MyUser
from accounts.thread_local import clear_current_user, set_current_user


class LogEntryProtectionTest(TestCase):
    def setUp(self):
        self.operator = MyUser.objects.create_user(
            email='operator@example.com', username='operator', password='pass',
            is_active=True, is_dashboard_user=True,
        )
        self.log_entry = LogEntry.objects.create(
            user=self.operator,
            content_type=ContentType.objects.get_for_model(MyUser),
            object_id=str(self.operator.pk),
            object_repr=str(self.operator),
            action_flag=ADDITION,
            change_message='created',
        )

    def tearDown(self):
        clear_current_user()

    def test_non_superuser_cannot_modify_existing_log(self):
        set_current_user(self.operator)
        self.log_entry.change_message = 'tampered'
        with self.assertRaises(PermissionDenied):
            self.log_entry.save(update_fields=['change_message'])

    def test_non_superuser_cannot_delete_existing_log(self):
        set_current_user(self.operator)
        with self.assertRaises(PermissionDenied):
            self.log_entry.delete()
