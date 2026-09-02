from datetime import datetime, timezone as datetime_timezone

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from Blogs.models import Category, Post, PostVisit
from PowerAdapterBlogs.dashboard_context import _hourly_visits
from accounts.models import MyUser
from boards.models import Board, BoardMembership
from comment.models import Comment


class DevenirDashboardTest(TestCase):
    password = "dashboard-test-password"

    @classmethod
    def setUpTestData(cls):
        cls.user = MyUser.objects.create_user(
            email="dashboard-ui@example.test",
            username="dashboard-ui",
            password=cls.password,
            is_active=True,
            is_dashboard_user=True,
        )
        cls.category = Category.objects.create(
            name="Coding",
            owner=cls.user,
            status=Category.STATUS_NORMAL,
        )
        cls.published = Post.objects.create(
            title="Published",
            desc="published",
            content="body",
            slug="dashboard-published",
            category=cls.category,
            owner=cls.user,
            status=Post.STATUS_NORMAL,
        )
        cls.draft = Post.objects.create(
            title="Draft",
            desc="draft",
            content="body",
            slug="dashboard-draft",
            category=cls.category,
            owner=cls.user,
            status=Post.STATUS_DRAFT,
        )
        cls.board = Board.objects.create(
            slug="coding",
            name="Coding",
            category=cls.category,
        )
        BoardMembership.objects.create(
            board=cls.board,
            user=cls.user,
            role=BoardMembership.Role.EDITOR,
            created_by=cls.user,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_dashboard_index_uses_devenir_overview_and_real_counts(self):
        self.assertEqual(reverse("dashboard:overview"), "/dashboard/")
        response = self.client.get(reverse("dashboard:overview"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/dashboard/overview.html")
        self.assertContains(response, "控制台总览")
        self.assertContains(response, "1 已发布")
        self.assertContains(response, "0 个媒体资源")
        self.assertContains(response, reverse("index"))
        self.assertContains(response, reverse("accounts:my-profile"))
        self.assertContains(response, reverse("accounts:mfa-settings"))
        self.assertContains(response, reverse("cus_admin:index"))
        self.assertContains(response, "滇ICP备2025068499号-1")
        self.assertContains(response, "滇公网安备53010302001568号")
        self.assertNotContains(response, reverse("operations:security"))

    def test_security_navigation_uses_existing_server_permission(self):
        permission = Permission.objects.get(codename="view_audit_log")
        self.user.user_permissions.add(permission)

        response = self.client.get(reverse("dashboard:overview"))

        self.assertContains(response, reverse("operations:security"))

    def test_anonymous_dashboard_request_keeps_canonical_next_target(self):
        self.client.logout()

        response = self.client.get(reverse("dashboard:overview"))

        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next=%2Fdashboard%2F',
        )

    def test_audience_buckets_use_project_local_time(self):
        visit = PostVisit.objects.create(
            uid="timezone-boundary",
            post=self.published,
            visit_type=PostVisit.PV_VISIT,
        )
        utc_timestamp = datetime(
            2026,
            8,
            13,
            16,
            30,
            tzinfo=datetime_timezone.utc,
        )
        PostVisit.objects.filter(pk=visit.pk).update(created_time=utc_timestamp)

        buckets = _hourly_visits(
            datetime(2026, 8, 13, tzinfo=datetime_timezone.utc),
            Post.objects.filter(pk=self.published.pk),
        )

        self.assertEqual(buckets[0], 1)
        self.assertEqual(buckets[5], 0)

    def test_first_party_pages_keep_dashboard_permission_boundary(self):
        for name in ("posts", "audit", "media"):
            with self.subTest(name=name):
                response = self.client.get(reverse(f"dashboard:{name}"))
                self.assertEqual(response.status_code, 200)

        self.assertEqual(
            self.client.get(reverse("dashboard:settings")).status_code,
            403,
        )

        regular = MyUser.objects.create_user(
            email="regular-ui@example.test",
            username="regular-ui",
            password=self.password,
            is_active=True,
        )
        self.client.force_login(regular)
        response = self.client.get(reverse("dashboard:posts"))
        self.assertEqual(response.status_code, 403)

    def test_dashboard_shell_does_not_grant_page_capabilities(self):
        shell_only = MyUser.objects.create_user(
            email="shell-only@example.test",
            username="shell-only",
            password=self.password,
            is_active=True,
            is_dashboard_user=True,
        )
        self.client.force_login(shell_only)

        overview = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(overview.status_code, 200)
        self.assertNotContains(overview, reverse("cus_admin:index"))
        compatibility = self.client.get(reverse("cus_admin:index"))
        self.assertEqual(compatibility.status_code, 302)
        for name in ("posts", "audit", "comments", "media", "settings"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(reverse(f"dashboard:{name}")).status_code,
                    403,
                )
                self.assertNotContains(
                    overview,
                    reverse(f"dashboard:{name}"),
                )

    def test_site_settings_are_visible_only_to_site_owner(self):
        owner = MyUser.objects.create_superuser(
            email="dashboard-owner@example.test",
            username="dashboard-owner",
            password=self.password,
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("dashboard:settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "站点设置")

    def test_legacy_admin_is_available_only_at_compatibility_route(self):
        compatibility_url = reverse("cus_admin:index")

        self.assertEqual(compatibility_url, "/dashboard/compatibility/")
        response = self.client.get(compatibility_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/index.html")
        self.assertNotContains(response, "控制台总览")

    def test_comment_navigation_and_counts_are_hidden_without_policy(self):
        response = self.client.get(reverse("dashboard:overview"))

        self.assertNotContains(response, "Comments</a>")
        self.assertContains(response, "当前账号没有评论审核权限")

    def test_comment_page_appears_with_board_moderation_permission(self):
        permission = Permission.objects.get(codename="change_comment")
        self.user.user_permissions.add(permission)

        # A global model permission must not replace Board-scoped moderation.
        response = self.client.get(reverse("dashboard:overview"))
        self.assertNotContains(response, "Comments</a>")

    def test_dashboard_lists_and_counts_stay_inside_board_scope(self):
        membership = BoardMembership.objects.get(board=self.board, user=self.user)
        membership.role = BoardMembership.Role.REVIEWER
        membership.save(update_fields=["role", "updated_at"])
        outsider = MyUser.objects.create_user(
            email="outside@example.test",
            username="outside",
            password=self.password,
            is_active=True,
        )
        other_category = Category.objects.create(
            name="Private",
            owner=outsider,
            status=Category.STATUS_NORMAL,
        )
        hidden_post = Post.objects.create(
            title="Hidden board post",
            desc="must remain scoped",
            content="body",
            slug="hidden-board-post",
            category=other_category,
            owner=outsider,
            status=Post.STATUS_NORMAL,
        )
        Board.objects.create(
            slug="private",
            name="Private",
            category=other_category,
        )
        Comment.objects.create(
            post=self.published,
            user=outsider,
            content="Visible scoped comment",
        )
        Comment.objects.create(
            post=hidden_post,
            user=outsider,
            content="Hidden cross-board comment",
        )

        overview = self.client.get(reverse("dashboard:overview"))
        posts = self.client.get(reverse("dashboard:posts"))
        comments = self.client.get(reverse("dashboard:comments"))

        self.assertEqual(overview.context["content_pulse"]["published_count"], 1)
        self.assertContains(posts, "Published")
        self.assertNotContains(posts, "Hidden board post")
        self.assertContains(comments, "Visible scoped comment")
        self.assertNotContains(comments, "Hidden cross-board comment")
