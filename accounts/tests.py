import re
from datetime import timedelta

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.admin import CusMyUserAdmin
from accounts.forms import AccountInvitationCreationForm
from accounts.models import AccountInvitation, MyUser, UserProfile
from accounts.services import (
    PASSWORD_EMAIL_VERIFIED_SESSION_KEY,
    issue_account_invitation,
)
from Blogs.models import Category, Post
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


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PUBLIC_SITE_URL="https://blog.example.test",
    ACCOUNT_INVITATION_TTL_SECONDS=3600,
    ACCOUNT_VERIFIED_GROUP_NAME="VerifiedUsers",
)
class AccountInvitationTest(TestCase):
    password = "a-long-and-uncommon-test-password-2026"

    def test_admin_creation_form_never_accepts_or_sets_a_password(self):
        form = AccountInvitationCreationForm(
            data={"username": "invited", "email": "invited@example.test"}
        )

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())

    def test_invitation_email_is_sent_only_after_commit(self):
        user = MyUser.objects.create_user(
            email="mail@example.test",
            username="mail-user",
            password=None,
            is_active=False,
        )

        with self.captureOnCommitCallbacks(execute=True):
            invitation, token = issue_account_invitation(user)

        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(user.email, mail.outbox[0].to)
        self.assertIn(
            reverse("accounts:accept-invitation", kwargs={"token": token}),
            mail.outbox[0].body,
        )
        self.assertNotIn(token, invitation.token_digest)

    def test_accepting_invitation_activates_user_and_is_single_use(self):
        user = MyUser.objects.create_user(
            email="activate@example.test",
            username="activate-user",
            password=None,
            is_active=False,
        )
        invitation, token = issue_account_invitation(user)
        url = reverse("accounts:accept-invitation", kwargs={"token": token})

        response = self.client.post(
            url,
            {"new_password1": self.password, "new_password2": self.password},
        )

        self.assertRedirects(response, reverse("accounts:login"))
        user.refresh_from_db()
        invitation.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(self.password))
        self.assertIsNotNone(invitation.accepted_at)
        self.assertTrue(user.groups.filter(name="VerifiedUsers").exists())
        self.assertEqual(self.client.get(url).status_code, 400)

    def test_resending_invitation_invalidates_previous_link(self):
        user = MyUser.objects.create_user(
            email="resend@example.test",
            username="resend-user",
            password=None,
            is_active=False,
        )
        _, old_token = issue_account_invitation(user)
        _, new_token = issue_account_invitation(user)

        old_url = reverse("accounts:accept-invitation", kwargs={"token": old_token})
        new_url = reverse("accounts:accept-invitation", kwargs={"token": new_token})
        self.assertEqual(self.client.get(old_url).status_code, 400)
        self.assertEqual(self.client.get(new_url).status_code, 200)
        self.assertEqual(AccountInvitation.objects.filter(user=user).count(), 1)

    def test_super_admin_adds_an_invited_account_without_password_fields(self):
        root = MyUser.objects.create_superuser(
            email="root-invite@example.test",
            username="root-invite",
            password=self.password,
        )
        self.client.force_login(root)
        add_url = reverse("admin:accounts_myuser_add")

        response = self.client.get(add_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="password1"')
        self.assertNotContains(response, 'name="password2"')

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                add_url,
                {
                    "username": "admin-invited",
                    "email": "admin-invited@example.test",
                    "_save": "保存",
                },
            )

        self.assertEqual(
            response.status_code,
            302,
            response.context["adminform"].form.errors if response.context else None,
        )
        invited = MyUser.objects.get(username="admin-invited")
        self.assertFalse(invited.is_active)
        self.assertFalse(invited.has_usable_password())
        self.assertTrue(AccountInvitation.objects.filter(user=invited).exists())
        self.assertEqual(len(mail.outbox), 1)


@override_settings(
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "sessions": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    },
)
class UserProfileTest(TestCase):
    old_password = "old-profile-password-2026"
    new_password = "new-profile-password-2026"

    def setUp(self):
        cache.clear()
        self.owner = MyUser.objects.create_user(
            email="profile-owner@example.test",
            username="profile-owner",
            password=self.old_password,
            is_active=True,
        )
        self.other = MyUser.objects.create_user(
            email="profile-other@example.test",
            username="profile-other",
            password=self.old_password,
            is_active=True,
        )
        self.profile = UserProfile.objects.create(
            user=self.owner,
            display_name="Profile Owner",
            bio="公开简介",
            is_public=False,
        )
        self.category = Category.objects.create(name="Profile", owner=self.owner)
        self.public_post = Post.objects.create(
            title="公开文章",
            content="public",
            category=self.category,
            owner=self.owner,
            status=Post.STATUS_NORMAL,
            visibility=Post.VISIBILITY_PUBLIC,
        )
        self.internal_post = Post.objects.create(
            title="内部文章",
            content="internal",
            category=self.category,
            owner=self.owner,
            status=Post.STATUS_NORMAL,
            visibility=Post.VISIBILITY_STAFF_ONLY,
        )
        self.draft_post = Post.objects.create(
            title="草稿文章",
            content="draft",
            category=self.category,
            owner=self.owner,
            status=Post.STATUS_DRAFT,
            visibility=Post.VISIBILITY_PUBLIC,
        )

    @property
    def detail_url(self):
        return reverse(
            "accounts:profile-detail",
            kwargs={"username": self.owner.username},
        )

    def _send_password_change_code(self):
        response = self.client.post(
            reverse("accounts:password-email-verify"),
            {"action": "send"},
        )
        self.assertRedirects(response, reverse("accounts:password-email-verify"))
        self.assertTrue(mail.outbox)
        match = re.search(r"(?<!\d)(\d{6})(?!\d)", mail.outbox[-1].body)
        self.assertIsNotNone(match)
        return match.group(1)

    def _verify_password_change_email(self):
        code = self._send_password_change_code()
        response = self.client.post(
            reverse("accounts:password-email-verify"),
            {"code": code},
        )
        self.assertRedirects(response, reverse("accounts:password-change"))

    def test_private_profile_is_404_to_others_but_visible_to_owner(self):
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)

        self.client.force_login(self.owner)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "当前为私人预览")

    def test_public_profile_exposes_only_public_identity_and_posts(self):
        self.profile.is_public = True
        self.profile.save(update_fields=("is_public", "updated_at"))
        self.owner.groups.create(name="SensitiveRoleName")

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.profile.display_name)
        self.assertContains(response, self.public_post.title)
        self.assertNotContains(response, self.internal_post.title)
        self.assertNotContains(response, self.draft_post.title)
        self.assertNotContains(response, self.owner.email)
        self.assertNotContains(response, "SensitiveRoleName")

    def test_my_profile_creates_private_profile_and_redirects(self):
        UserProfile.objects.filter(user=self.other).delete()
        self.client.force_login(self.other)

        response = self.client.get(reverse("accounts:my-profile"))

        profile = UserProfile.objects.get(user=self.other)
        self.assertRedirects(response, profile.get_absolute_url())
        self.assertFalse(profile.is_public)

    def test_profile_update_is_bound_to_request_user(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("accounts:profile-update"),
            {
                "display_name": "Updated Owner",
                "bio": "新的简介",
                "website": "https://example.test/owner",
                "github_url": "https://github.com/example",
                "location": "Chengdu",
                "is_public": "on",
                "user": self.other.pk,
            },
        )

        self.assertRedirects(response, self.detail_url)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user, self.owner)
        self.assertEqual(self.profile.display_name, "Updated Owner")
        self.assertTrue(self.profile.is_public)
        self.assertFalse(UserProfile.objects.filter(user=self.other).exists())

    def test_profile_rejects_fake_avatar(self):
        self.client.force_login(self.owner)
        fake_image = SimpleUploadedFile(
            "avatar.png",
            b"not-a-real-image",
            content_type="image/png",
        )

        response = self.client.post(
            reverse("accounts:profile-update"),
            {
                "display_name": "Profile Owner",
                "bio": "公开简介",
                "website": "",
                "github_url": "",
                "location": "",
                "avatar": fake_image,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "上传文件不是有效图片")
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.avatar)

    def test_profile_update_keeps_existing_avatar_without_revalidating_upload(self):
        self.profile.avatar.name = "profile-avatars/existing-avatar.png"
        self.profile.save(update_fields=("avatar", "updated_at"))
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("accounts:profile-update"),
            {
                "display_name": "Existing Avatar",
                "bio": "Keep the stored image.",
                "website": "",
                "github_url": "",
                "location": "Chengdu",
            },
        )

        self.assertRedirects(response, self.detail_url)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.avatar.name, "profile-avatars/existing-avatar.png")

    def test_password_change_keeps_session_and_invalidates_old_password(self):
        self.client.force_login(self.owner)
        self._verify_password_change_email()

        response = self.client.post(
            reverse("accounts:password-change"),
            {
                "old_password": self.old_password,
                "new_password1": self.new_password,
                "new_password2": self.new_password,
            },
        )

        self.assertRedirects(response, self.detail_url)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.check_password(self.old_password))
        self.assertTrue(self.owner.check_password(self.new_password))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.owner.pk)
        self.assertNotIn(PASSWORD_EMAIL_VERIFIED_SESSION_KEY, self.client.session)

    def test_password_change_requires_email_verification(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("accounts:password-change"))

        self.assertRedirects(response, reverse("accounts:password-email-verify"))

    def test_profile_password_link_starts_fresh_email_verification(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.detail_url)

        expected = f'{reverse("accounts:password-email-verify")}?restart=1'
        self.assertContains(response, f'href="{expected}"')

    def test_restart_email_verification_clears_previous_grant(self):
        self.client.force_login(self.owner)
        self._verify_password_change_email()

        response = self.client.get(
            reverse("accounts:password-email-verify"),
            {"restart": "1"},
        )

        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("accounts:password-change"))
        self.assertRedirects(response, reverse("accounts:password-email-verify"))

    def test_password_change_renders_rotation_console_after_verification(self):
        self.client.force_login(self.owner)
        self._verify_password_change_email()

        response = self.client.get(reverse("accounts:password-change"))

        self.assertContains(response, "CREDENTIAL ROTATION PROTOCOL")
        self.assertContains(response, "data-credential-console")
        self.assertContains(response, "password_rotation.js")

    def test_password_email_code_has_resend_cooldown(self):
        self.client.force_login(self.owner)
        self._send_password_change_code()

        response = self.client.post(
            reverse("accounts:password-email-verify"),
            {"action": "send"},
            follow=True,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(response, "发送过于频繁")

    def test_password_email_page_exposes_resend_and_expiry_countdowns(self):
        self.client.force_login(self.owner)
        self._send_password_change_code()

        response = self.client.get(reverse("accounts:password-email-verify"))

        self.assertGreater(response.context["resend_remaining"], 0)
        self.assertLessEqual(
            response.context["resend_remaining"],
            settings.PASSWORD_EMAIL_SEND_COOLDOWN_SECONDS,
        )
        self.assertGreater(response.context["code_remaining"], 0)
        self.assertLessEqual(
            response.context["code_remaining"],
            settings.PASSWORD_EMAIL_CODE_TTL_SECONDS,
        )
        self.assertContains(response, "data-resend-countdown")
        self.assertContains(response, "data-code-countdown")
        self.assertContains(response, "password_email_verification.js")

    @override_settings(PASSWORD_EMAIL_SEND_COOLDOWN_SECONDS=0)
    def test_password_email_code_limits_hourly_sends(self):
        self.client.force_login(self.owner)
        url = reverse("accounts:password-email-verify")

        for _ in range(4):
            response = self.client.post(url, {"action": "send"}, follow=True)

        self.assertEqual(len(mail.outbox), 3)
        self.assertContains(response, "本小时发送次数已用完")

    def test_password_email_code_locks_after_wrong_attempts(self):
        self.client.force_login(self.owner)
        code = self._send_password_change_code()
        wrong_code = "111111" if code == "000000" else "000000"
        url = reverse("accounts:password-email-verify")

        for _ in range(5):
            response = self.client.post(url, {"code": wrong_code})

        self.assertContains(response, "错误次数已用完")
        response = self.client.post(url, {"code": code})
        self.assertContains(response, "不存在或已过期")

    def test_password_email_code_is_bound_to_requesting_session(self):
        self.client.force_login(self.owner)
        code = self._send_password_change_code()
        another_session = Client()
        another_session.force_login(self.owner)

        response = another_session.post(
            reverse("accounts:password-email-verify"),
            {"code": code},
        )

        self.assertContains(response, "不存在或已过期")
        response = self.client.post(
            reverse("accounts:password-email-verify"),
            {"code": code},
        )
        self.assertRedirects(response, reverse("accounts:password-change"))

    def test_password_email_verification_grant_expires(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session[PASSWORD_EMAIL_VERIFIED_SESSION_KEY] = {
            "user_id": self.owner.pk,
            "verified_at": (timezone.now() - timedelta(minutes=11)).timestamp(),
        }
        session.save()

        response = self.client.get(reverse("accounts:password-change"))

        self.assertRedirects(response, reverse("accounts:password-email-verify"))

    def test_post_author_links_only_to_public_profile(self):
        detail_url = self.public_post.get_absolute_url()
        self.profile.avatar.name = "profile-avatars/private-avatar.png"
        self.profile.save(update_fields=("avatar", "updated_at"))

        private_response = self.client.get(detail_url)
        self.assertNotContains(private_response, self.detail_url)
        self.assertNotContains(private_response, self.profile.avatar.url)

        self.profile.is_public = True
        self.profile.save(update_fields=("is_public", "updated_at"))
        public_response = self.client.get(detail_url)
        self.assertContains(public_response, self.detail_url)
