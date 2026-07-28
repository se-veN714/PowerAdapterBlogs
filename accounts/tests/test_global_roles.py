"""Stage 6a tests for fixed global groups and permissions."""

from importlib import import_module

from django.apps import apps
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from PowerAdapterBlogs.base_admin import has_dashboard_access
from PowerAdapterBlogs.cus_site import custom_site
from accounts.admin import CusMyUserAdmin
from accounts.models import MyUser
from boards.models import Board
from boards.policies import can_create_post
from security.admin import SecureLogEntryAdmin
from security.models import SecureLogEntry


class GlobalGroupProvisioningTest(TestCase):
    expected_permissions = {
        "VerifiedUsers": {("boards", "apply_board_access")},
        "UserManagers": {("accounts", "manage_user_accounts")},
        "SiteOperators": {
            ("security", "view_audit_log"),
            ("security", "run_integrity_audit"),
        },
    }

    def test_fixed_groups_have_only_their_declared_permissions(self):
        for group_name, expected in self.expected_permissions.items():
            with self.subTest(group_name=group_name):
                group = Group.objects.get(name=group_name)
                actual = set(
                    group.permissions.values_list(
                        "content_type__app_label",
                        "codename",
                    )
                )
                self.assertEqual(actual, expected)

    def test_initializer_is_idempotent_and_migrates_only_safe_legacy_roles(self):
        active_user = self.create_user("active")
        legacy_staff = self.create_user("legacy-staff", is_staff=True)
        inactive_user = self.create_user("inactive", is_active=False)
        legacy_reviewer = self.create_user("legacy-reviewer", is_reviewer=True)
        initializer = import_module(
            "accounts.migrations.0006_initialize_global_groups"
        ).initialize_global_groups

        initializer(apps, None)
        initializer(apps, None)

        self.assertTrue(active_user.groups.filter(name="VerifiedUsers").exists())
        self.assertTrue(legacy_staff.groups.filter(name="VerifiedUsers").exists())
        self.assertTrue(legacy_staff.groups.filter(name="UserManagers").exists())
        self.assertFalse(inactive_user.groups.exists())
        self.assertFalse(legacy_reviewer.groups.filter(name="SiteOperators").exists())

    @staticmethod
    def create_user(username, **extra_fields):
        extra_fields.setdefault("is_active", True)
        return MyUser.objects.create_user(
            email=f"{username}@example.test",
            username=username,
            password="test-password",
            **extra_fields,
        )


class GlobalRoleRuntimeBoundaryTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.account_admin = CusMyUserAdmin(MyUser, AdminSite())
        self.audit_admin = SecureLogEntryAdmin(SecureLogEntry, AdminSite())
        self.root = MyUser.objects.create_superuser(
            email="root@example.test",
            username="root",
            password="test-password",
        )

    def create_group_user(self, username, group_name):
        user = MyUser.objects.create_user(
            email=f"{username}@example.test",
            username=username,
            password="test-password",
            is_active=True,
        )
        user.groups.add(Group.objects.get(name=group_name))
        return user

    def request_for(self, user, path="/dashboard/"):
        request = self.factory.get(path)
        request.user = user
        return request

    def test_verified_user_can_apply_but_gets_no_board_crud(self):
        user = self.create_group_user("verified", "VerifiedUsers")
        board = Board.objects.create(slug="coding", name="Coding")

        self.assertTrue(user.has_perm("boards.apply_board_access"))
        self.assertFalse(user.has_perm("boards.add_board"))
        self.assertFalse(user.has_perm("Blogs.add_post"))
        self.assertFalse(can_create_post(user, board))
        self.assertFalse(has_dashboard_access(user))

    def test_user_manager_gets_scoped_account_management_only(self):
        manager = self.create_group_user("user-manager", "UserManagers")
        target = MyUser.objects.create_user(
            email="target@example.test",
            username="target",
            password="test-password",
            is_active=True,
        )
        request = self.request_for(manager, "/dashboard/accounts/myuser/")

        self.assertTrue(custom_site.has_permission(request))
        self.assertTrue(self.account_admin.has_module_permission(request))
        self.assertTrue(self.account_admin.has_change_permission(request, target))
        self.assertFalse(self.account_admin.has_view_permission(request, self.root))
        self.assertFalse(self.account_admin.has_change_permission(request, self.root))
        self.assertFalse(self.account_admin.has_add_permission(request))
        self.assertFalse(self.account_admin.has_delete_permission(request, target))
        self.assertNotIn(
            self.root,
            self.account_admin.get_queryset(request),
        )
        self.assertNotIn(
            "resend_account_invitation",
            self.account_admin.get_actions(request),
        )
        self.assertFalse(manager.has_perm("security.view_audit_log"))

    def test_site_operator_gets_audit_view_and_action_only(self):
        operator = self.create_group_user("site-operator", "SiteOperators")
        request = self.request_for(operator, "/dashboard/security/securelogentry/")

        self.assertTrue(custom_site.has_permission(request))
        self.assertTrue(self.audit_admin.has_module_permission(request))
        self.assertTrue(self.audit_admin.has_view_permission(request))
        self.assertTrue(self.audit_admin.has_run_integrity_audit_permission(request))
        self.assertFalse(self.audit_admin.has_change_permission(request))
        self.assertFalse(operator.has_perm("accounts.manage_user_accounts"))

    def test_dashboard_flag_alone_does_not_expose_audit_log(self):
        dashboard_user = MyUser.objects.create_user(
            email="dashboard@example.test",
            username="dashboard",
            password="test-password",
            is_active=True,
            is_dashboard_user=True,
        )
        request = self.request_for(
            dashboard_user,
            "/dashboard/security/securelogentry/",
        )

        self.assertTrue(custom_site.has_permission(request))
        self.assertFalse(self.audit_admin.has_module_permission(request))
        self.assertFalse(self.audit_admin.has_view_permission(request))
        self.assertFalse(self.audit_admin.has_run_integrity_audit_permission(request))

    def test_legacy_reviewer_flag_grants_no_runtime_access(self):
        legacy_reviewer = MyUser.objects.create_user(
            email="legacy-reviewer-runtime@example.test",
            username="legacy-reviewer-runtime",
            password="test-password",
            is_active=True,
            is_reviewer=True,
        )
        board = Board.objects.create(slug="legacy-flag", name="Legacy flag")
        request = self.request_for(legacy_reviewer)

        self.assertFalse(has_dashboard_access(legacy_reviewer))
        self.assertFalse(custom_site.has_permission(request))
        self.assertFalse(can_create_post(legacy_reviewer, board))
        self.assertFalse(
            legacy_reviewer.has_perm("accounts.manage_user_accounts")
        )
        self.assertFalse(legacy_reviewer.has_perm("security.view_audit_log"))
