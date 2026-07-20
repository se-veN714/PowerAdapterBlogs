from django.contrib.admin.sites import AdminSite
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.admin import CusMyUserAdmin
from accounts.models import MyUser
from PowerAdapterBlogs.cus_site import custom_site


@override_settings(
    CACHES={
        'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
        'sessions': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    },
    LOGIN_MAX_FAILURES=3,
    LOGIN_LOCKOUT_SECONDS=60,
)
class LoginLockoutTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = MyUser.objects.create_user(
            email='user@example.com', username='user', password='correct', is_active=True
        )
        self.url = reverse('accounts:login')

    def test_repeated_failures_lock_matching_username_and_ip(self):
        for _ in range(3):
            self.client.post(self.url, {'username': 'user', 'password': 'wrong'})

        response = self.client.post(self.url, {'username': 'user', 'password': 'correct'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '登录失败次数过多')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_successful_login_clears_failure_counter(self):
        self.client.post(self.url, {'username': 'user', 'password': 'wrong'})
        response = self.client.post(self.url, {'username': 'user', 'password': 'correct'})
        self.assertEqual(response.status_code, 302)
        self.client.logout()

        self.client.post(self.url, {'username': 'user', 'password': 'wrong'})
        response = self.client.post(self.url, {'username': 'user', 'password': 'correct'})
        self.assertEqual(response.status_code, 302)


class DashboardAccountAdminBoundaryTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.model_admin = CusMyUserAdmin(MyUser, AdminSite())

    def request_for(self, user):
        request = self.factory.get('/dashboard/accounts/myuser/')
        request.user = user
        return request

    def test_dashboard_flag_does_not_grant_global_account_management(self):
        board_user = MyUser.objects.create_user(
            email='board-user@example.com',
            username='board-user',
            password='test-password',
            is_active=True,
            is_dashboard_user=True,
        )
        request = self.request_for(board_user)

        self.assertFalse(self.model_admin.has_module_permission(request))
        self.assertFalse(self.model_admin.has_view_permission(request))
        self.assertFalse(self.model_admin.has_change_permission(request))
        self.assertFalse(self.model_admin.has_add_permission(request))
        self.assertFalse(self.model_admin.has_delete_permission(request))

    def test_active_superuser_keeps_account_management_access(self):
        superuser = MyUser.objects.create_superuser(
            email='account-root@example.com',
            username='account-root',
            password='test-password',
        )
        superuser.is_dashboard_user = False
        superuser.save(update_fields=['is_dashboard_user'])
        request = self.request_for(superuser)

        self.assertTrue(custom_site.has_permission(request))
        self.assertTrue(self.model_admin.has_module_permission(request))
        self.assertTrue(self.model_admin.has_view_permission(request))
        self.assertTrue(self.model_admin.has_change_permission(request))
        self.assertTrue(self.model_admin.has_add_permission(request))
        self.assertTrue(self.model_admin.has_delete_permission(request))


class DashboardLoginTest(TestCase):
    def setUp(self):
        self.password = 'case-sensitive-password'
        self.dashboard_user = MyUser.objects.create_user(
            email='dashboard-login@example.com',
            username='dashboard-login',
            password=self.password,
            is_active=True,
            is_dashboard_user=True,
        )

    def test_non_staff_dashboard_user_can_log_in_to_custom_admin(self):
        response = self.client.post(
            reverse('cus_admin:login'),
            {'username': self.dashboard_user.username, 'password': self.password},
        )

        self.assertRedirects(response, reverse('cus_admin:index'))
        self.assertEqual(
            int(self.client.session['_auth_user_id']),
            self.dashboard_user.pk,
        )

    def test_dashboard_user_cannot_log_in_to_system_admin(self):
        response = self.client.post(
            reverse('admin:login'),
            {'username': self.dashboard_user.username, 'password': self.password},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(response, '工作人员账户')

    def test_dashboard_login_remains_case_sensitive(self):
        response = self.client.post(
            reverse('cus_admin:login'),
            {'username': self.dashboard_user.username.upper(), 'password': self.password},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
