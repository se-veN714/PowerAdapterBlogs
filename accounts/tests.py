from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import MyUser


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
