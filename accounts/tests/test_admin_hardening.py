"""H0 regression tests for privileged administration entry points."""

from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, TestCase
from django.urls import reverse

from PowerAdapterBlogs.admin_site import SuperuserAdminSite
from PowerAdapterBlogs.cus_site import DASHBOARD_MODEL_ALLOWLIST, custom_site
from accounts.models import MyUser


class PrivilegedAdminEntryBoundaryTest(TestCase):
    password = "case-sensitive-password"

    @classmethod
    def setUpTestData(cls):
        cls.regular_user = cls.create_user("regular")
        cls.dashboard_user = cls.create_user(
            "dashboard",
            is_dashboard_user=True,
        )
        cls.staff_user = cls.create_user("staff", is_staff=True)
        cls.superuser = MyUser.objects.create_superuser(
            email="root@example.test",
            username="root",
            password=cls.password,
        )
        cls.superuser.is_dashboard_user = False
        cls.superuser.save(update_fields=["is_dashboard_user"])
        cls.inactive_superuser = MyUser.objects.create_superuser(
            email="inactive-root@example.test",
            username="inactive-root",
            password=cls.password,
        )
        cls.inactive_superuser.is_active = False
        cls.inactive_superuser.save(update_fields=["is_active"])

    @classmethod
    def create_user(cls, username, **extra_fields):
        return MyUser.objects.create_user(
            email=f"{username}@example.test",
            username=username,
            password=cls.password,
            is_active=True,
            **extra_fields,
        )

    def assert_entry_denied(self, *, user, entry_url, login_url):
        self.client.force_login(user)
        response = self.client.get(entry_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(login_url))
        self.client.logout()

    def test_default_admin_uses_superuser_only_site(self):
        self.assertIsInstance(admin.site, SuperuserAdminSite)

    def test_dashboard_registry_matches_explicit_model_allowlist(self):
        registered_labels = {
            model._meta.label_lower.lower() for model in custom_site._registry
        }
        self.assertEqual(registered_labels, DASHBOARD_MODEL_ALLOWLIST)

    def test_dashboard_rejects_unapproved_model_registration(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "Models are not approved for /dashboard/: accounts.myuser",
        ):
            custom_site.register(MyUser)

    def test_anonymous_user_is_redirected_to_each_matching_login(self):
        cases = (
            (reverse("admin:index"), reverse("admin:login")),
            (reverse("cus_admin:index"), reverse("cus_admin:login")),
        )
        for entry_url, login_url in cases:
            with self.subTest(entry_url=entry_url):
                response = self.client.get(entry_url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(login_url))

    def test_regular_dashboard_and_staff_only_users_cannot_enter_system_admin(self):
        entry_url = reverse("admin:index")
        login_url = reverse("admin:login")
        for user in (self.regular_user, self.dashboard_user, self.staff_user):
            with self.subTest(username=user.username):
                self.assert_entry_denied(
                    user=user,
                    entry_url=entry_url,
                    login_url=login_url,
                )

    def test_only_dashboard_user_and_superuser_can_enter_dashboard(self):
        entry_url = reverse("cus_admin:index")
        login_url = reverse("cus_admin:login")
        for user in (self.regular_user, self.staff_user):
            with self.subTest(username=user.username):
                self.assert_entry_denied(
                    user=user,
                    entry_url=entry_url,
                    login_url=login_url,
                )

        for user in (self.dashboard_user, self.superuser):
            with self.subTest(username=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(entry_url).status_code, 200)
                self.client.logout()

    def test_active_superuser_can_enter_system_admin(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_newest_superuser_login_invalidates_older_browser_session(self):
        chrome = Client()
        edge = Client()
        chrome.force_login(self.superuser)
        self.assertEqual(chrome.get(reverse("admin:index")).status_code, 200)

        edge.force_login(self.superuser)
        self.assertEqual(edge.get(reverse("admin:index")).status_code, 200)
        retired = chrome.get(reverse("admin:index"))

        self.assertEqual(retired.status_code, 302)
        self.assertTrue(retired.url.startswith(reverse("accounts:login")))
        self.assertNotIn("_auth_user_id", chrome.session)

    def test_regular_user_sessions_remain_multi_device(self):
        first = Client()
        second = Client()
        first.force_login(self.regular_user)
        second.force_login(self.regular_user)

        self.assertEqual(first.get(reverse("index")).status_code, 200)
        self.assertEqual(second.get(reverse("index")).status_code, 200)
        self.assertIn("_auth_user_id", first.session)
        self.assertIn("_auth_user_id", second.session)

    def test_inactive_superuser_cannot_enter_either_admin_site(self):
        cases = (
            (reverse("admin:index"), reverse("admin:login")),
            (reverse("cus_admin:index"), reverse("cus_admin:login")),
        )
        for entry_url, login_url in cases:
            with self.subTest(entry_url=entry_url):
                self.assert_entry_denied(
                    user=self.inactive_superuser,
                    entry_url=entry_url,
                    login_url=login_url,
                )

    def test_staff_only_credentials_cannot_start_system_admin_session(self):
        response = self.client.post(
            reverse("admin:login"),
            {"username": self.staff_user.username, "password": self.password},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
