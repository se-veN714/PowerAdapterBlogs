"""Runtime Admin isolation contracts for accounts_linear stage 4."""

from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import MyUser
from Blogs.admin import PostAdmin, PostRevisionAdmin, PostWorkflowEventAdmin
from Blogs.models import Category, Post, PostRevision, PostWorkflowEvent
from boards.admin import BoardAdmin
from boards.models import Board, BoardMembership
from comment.admin import BoardScopedCommentAdmin
from comment.models import Comment


class BoardScopedAdminTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.owner = self.create_user("owner")
        self.other_owner = self.create_user("other-owner")
        self.member = self.create_user("member")

        self.category = Category.objects.create(name="Coding", owner=self.owner)
        self.other_category = Category.objects.create(
            name="Music",
            owner=self.other_owner,
        )
        self.board = Board.objects.create(
            slug="coding",
            name="Coding",
            category=self.category,
        )
        self.other_board = Board.objects.create(
            slug="music",
            name="Music",
            category=self.other_category,
        )
        self.own_post = self.create_post("Own", self.category, self.member)
        self.same_board_post = self.create_post(
            "Same Board",
            self.category,
            self.owner,
        )
        self.other_board_post = self.create_post(
            "Other Board",
            self.other_category,
            self.other_owner,
        )
        self.comment = self.create_comment(self.same_board_post, self.owner)
        self.other_comment = self.create_comment(
            self.other_board_post,
            self.other_owner,
        )

        self.post_admin = PostAdmin(Post, AdminSite())
        self.revision_admin = PostRevisionAdmin(PostRevision, AdminSite())
        self.workflow_event_admin = PostWorkflowEventAdmin(
            PostWorkflowEvent,
            AdminSite(),
        )
        self.board_admin = BoardAdmin(Board, AdminSite())
        self.comment_admin = BoardScopedCommentAdmin(Comment, AdminSite())

    def create_user(self, username):
        return MyUser.objects.create_user(
            email=f"{username}@example.com",
            username=username,
            password="test-password",
            is_active=True,
            is_dashboard_user=True,
        )

    @staticmethod
    def create_post(title, category, owner):
        return Post.objects.create(
            title=title,
            content="content",
            status=Post.STATUS_DRAFT,
            category=category,
            owner=owner,
        )

    @staticmethod
    def create_comment(post, user):
        return Comment.objects.create(
            post=post,
            user=user,
            nickname=user.username,
            content="comment",
        )

    def add_membership(self, role, *, user=None, board=None):
        return BoardMembership.objects.create(
            board=board or self.board,
            user=user or self.member,
            role=role,
        )

    def request_for(self, user, path="/dashboard/"):
        request = self.factory.get(path)
        request.user = user
        return request

    def test_editor_sees_only_own_posts_in_own_board(self):
        self.add_membership(BoardMembership.Role.EDITOR)
        request = self.request_for(self.member)

        queryset = self.post_admin.get_queryset(request)

        self.assertQuerySetEqual(queryset, [self.own_post])
        self.assertTrue(self.post_admin.has_change_permission(request, self.own_post))
        self.assertFalse(
            self.post_admin.has_change_permission(request, self.same_board_post)
        )
        self.assertFalse(
            self.post_admin.has_view_permission(request, self.other_board_post)
        )

    def test_reviewer_sees_all_posts_in_own_board_but_cannot_edit_them(self):
        self.add_membership(BoardMembership.Role.REVIEWER)
        request = self.request_for(self.member)

        queryset = self.post_admin.get_queryset(request)

        self.assertSetEqual(
            set(queryset),
            {self.own_post, self.same_board_post},
        )
        self.assertTrue(
            self.post_admin.has_view_permission(request, self.same_board_post)
        )
        self.assertFalse(
            self.post_admin.has_change_permission(request, self.same_board_post)
        )
        self.assertFalse(self.post_admin.has_add_permission(request))

    def test_manager_cannot_access_board_admin(self):
        """Board admin is superuser-only; managers get no access at all."""
        self.add_membership(BoardMembership.Role.MANAGER)
        request = self.request_for(self.member)

        self.assertFalse(self.board_admin.has_module_permission(request))
        self.assertFalse(self.board_admin.has_view_permission(request, self.board))
        self.assertFalse(self.board_admin.has_change_permission(request, self.board))
        self.assertFalse(self.board_admin.has_add_permission(request))
        self.assertFalse(self.board_admin.has_delete_permission(request, self.board))

    def test_post_form_only_accepts_categories_with_creation_membership(self):
        self.add_membership(BoardMembership.Role.EDITOR)
        request = self.request_for(self.member)

        form_class = self.post_admin.get_form(request)

        self.assertQuerySetEqual(
            form_class.base_fields["category"].queryset,
            [self.category],
        )

    def test_manager_edit_preserves_the_original_post_owner(self):
        self.add_membership(BoardMembership.Role.MANAGER)
        request = self.request_for(self.member)
        post = Post.objects.get(pk=self.same_board_post.pk)
        post.title = "Manager edit"

        self.post_admin.save_model(request, post, form=None, change=True)

        post.refresh_from_db()
        self.assertEqual(post.owner, self.owner)
        self.assertEqual(post.title, "Manager edit")

    def test_superuser_status_only_edit_records_event_without_revision(self):
        self.member.is_staff = True
        self.member.is_superuser = True
        self.member.save(update_fields=["is_staff", "is_superuser"])
        request = self.request_for(self.member)
        post = Post.objects.get(pk=self.own_post.pk)
        revision = self.create_revision(post, self.member)
        post.status = Post.STATUS_REVIEW

        self.post_admin.save_model(request, post, form=None, change=True)

        post.refresh_from_db()
        self.assertEqual(post.status, Post.STATUS_REVIEW)
        self.assertEqual(post.revisions.count(), 1)
        event = post.workflow_events.get()
        self.assertEqual(event.event_type, PostWorkflowEvent.EventType.SUBMITTED)
        self.assertEqual(event.revision, revision)
        self.assertEqual(event.actor, self.member)

    def test_comment_queue_is_readonly_and_scoped_to_reviewer_board(self):
        self.add_membership(BoardMembership.Role.REVIEWER)
        request = self.request_for(self.member)

        queryset = self.comment_admin.get_queryset(request)

        self.assertQuerySetEqual(queryset, [self.comment])
        self.assertTrue(self.comment_admin.has_view_permission(request, self.comment))
        self.assertFalse(
            self.comment_admin.has_view_permission(request, self.other_comment)
        )
        self.assertFalse(self.comment_admin.has_change_permission(request, self.comment))

    def test_admin_actions_follow_membership_role(self):
        membership = self.add_membership(BoardMembership.Role.EDITOR)
        request = self.request_for(self.member)

        editor_actions = self.post_admin.get_actions(request)
        self.assertIn("submit_for_review_action", editor_actions)
        self.assertNotIn("approve_review_action", editor_actions)

        membership.role = BoardMembership.Role.REVIEWER
        membership.save(update_fields=["role"])
        reviewer_actions = self.post_admin.get_actions(request)
        self.assertNotIn("submit_for_review_action", reviewer_actions)
        self.assertIn("approve_review_action", reviewer_actions)
        self.assertIn("reject_review_action", reviewer_actions)

    @patch("security.services.MongoLogger")
    def test_comment_action_moderates_only_the_reviewers_board(self, mongo_logger):
        self.add_membership(BoardMembership.Role.REVIEWER)
        request = self.request_for(self.member)
        request.session = {}
        request._messages = FallbackStorage(request)

        self.comment_admin.approve_comments(
            request,
            Comment.objects.filter(pk__in=[self.comment.pk, self.other_comment.pk]),
        )

        self.comment.refresh_from_db()
        self.other_comment.refresh_from_db()
        self.assertEqual(self.comment.status, Comment.Status.PUBLISHED)
        self.assertEqual(self.other_comment.status, Comment.Status.PENDING)
        mongo_logger.return_value.insert_log.assert_called_once()

    def test_post_revision_visibility_follows_its_post(self):
        self.add_membership(BoardMembership.Role.REVIEWER)
        own_revision = self.create_revision(self.same_board_post, self.owner)
        self.create_revision(self.other_board_post, self.other_owner)
        request = self.request_for(self.member)

        queryset = self.revision_admin.get_queryset(request)

        self.assertQuerySetEqual(queryset, [own_revision])

    def test_workflow_event_history_is_readonly_and_follows_post_scope(self):
        self.add_membership(BoardMembership.Role.REVIEWER)
        own_revision = self.create_revision(self.same_board_post, self.owner)
        other_revision = self.create_revision(
            self.other_board_post,
            self.other_owner,
        )
        own_event = PostWorkflowEvent.objects.create(
            post=self.same_board_post,
            actor=self.owner,
            event_type=PostWorkflowEvent.EventType.SUBMITTED,
            from_status=Post.STATUS_DRAFT,
            to_status=Post.STATUS_REVIEW,
            revision=own_revision,
        )
        other_event = PostWorkflowEvent.objects.create(
            post=self.other_board_post,
            actor=self.other_owner,
            event_type=PostWorkflowEvent.EventType.SUBMITTED,
            from_status=Post.STATUS_DRAFT,
            to_status=Post.STATUS_REVIEW,
            revision=other_revision,
        )
        request = self.request_for(self.member)

        queryset = self.workflow_event_admin.get_queryset(request)

        self.assertQuerySetEqual(queryset, [own_event])
        self.assertTrue(
            self.workflow_event_admin.has_view_permission(request, own_event)
        )
        self.assertFalse(
            self.workflow_event_admin.has_view_permission(request, other_event)
        )
        self.assertFalse(self.workflow_event_admin.has_add_permission(request))
        self.assertFalse(
            self.workflow_event_admin.has_change_permission(request, own_event)
        )
        self.assertFalse(
            self.workflow_event_admin.has_delete_permission(request, own_event)
        )

    def test_cross_board_change_url_cannot_reach_or_mutate_post(self):
        self.add_membership(BoardMembership.Role.MANAGER)
        self.client.force_login(self.member)
        url = reverse(
            f"cus_admin:{Post._meta.app_label}_{Post._meta.model_name}_change",
            args=[self.other_board_post.pk],
        )

        response = self.client.post(
            url,
            {
                "title": "Unauthorized change",
                "category": self.other_category.pk,
                "status": Post.STATUS_DRAFT,
                "desc": "",
                "content": "changed",
                "visibility": Post.VISIBILITY_PUBLIC,
                "tag": [],
            },
        )

        self.assertNotEqual(response.status_code, 200)
        self.other_board_post.refresh_from_db()
        self.assertEqual(self.other_board_post.title, "Other Board")
        self.assertEqual(self.other_board_post.content, "content")

    @staticmethod
    def create_revision(post, editor):
        return PostRevision.objects.create(
            post=post,
            major=1,
            minor=0,
            title=post.title,
            desc=post.desc,
            content=post.content,
            slug=post.slug,
            editor=editor,
            change_type="major",
            edit_summary="test",
        )
