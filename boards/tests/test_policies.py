"""ORM Policy contracts for accounts_linear stage 3."""

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from accounts.models import MyUser
from Blogs.models import Category, Post
from boards.models import Board, BoardMembership
from boards.policies import (
    board_for_comment,
    board_for_post,
    can_change_board_settings,
    can_change_board_structure,
    can_create_board,
    can_create_post,
    can_delete_board,
    can_edit_post,
    can_manage_board_members,
    can_moderate_comment,
    can_publish_post,
    can_review_post,
    can_submit_post,
    get_active_membership,
)
from comment.models import Comment


class BoardPolicyTest(TestCase):
    def setUp(self):
        self.owner = self.create_user("owner")
        self.other = self.create_user("other")
        self.category = Category.objects.create(name="Coding", owner=self.owner)
        self.board = Board.objects.create(
            slug="coding",
            name="Coding",
            category=self.category,
        )
        self.post = Post.objects.create(
            title="Policy Test",
            content="content",
            status=Post.STATUS_DRAFT,
            category=self.category,
            owner=self.owner,
        )
        self.comment = Comment.objects.create(
            post=self.post,
            user=self.other,
            nickname="other",
            content="comment",
        )

    def create_user(self, username, **extra_fields):
        return MyUser.objects.create_user(
            email=f"{username}@example.com",
            username=username,
            password="test-password",
            is_active=True,
            **extra_fields,
        )

    def add_membership(self, user, role, *, board=None, is_active=True):
        return BoardMembership.objects.create(
            board=board or self.board,
            user=user,
            role=role,
            is_active=is_active,
        )

    def test_post_and_comment_resolve_the_same_board(self):
        self.assertEqual(board_for_post(self.post), self.board)
        self.assertEqual(board_for_comment(self.comment), self.board)

    def test_missing_or_ambiguous_board_mapping_fails_closed(self):
        unmapped_category = Category.objects.create(
            name="Unmapped",
            owner=self.owner,
        )
        unmapped_post = Post.objects.create(
            title="Unmapped",
            content="content",
            category=unmapped_category,
            owner=self.owner,
        )
        self.assertIsNone(board_for_post(unmapped_post))

        Board.objects.create(
            slug="coding-copy",
            name="Coding Copy",
            category=self.category,
        )
        self.assertIsNone(board_for_post(self.post))

    def test_contributor_can_work_only_on_own_draft(self):
        self.add_membership(self.owner, BoardMembership.Role.CONTRIBUTOR)

        self.assertTrue(can_create_post(self.owner, self.board))
        self.assertTrue(can_edit_post(self.owner, self.post))
        self.assertTrue(can_submit_post(self.owner, self.post))
        self.assertFalse(can_edit_post(self.other, self.post))

        self.post.status = Post.STATUS_NORMAL
        self.post.save(update_fields=["status"])
        self.assertFalse(can_edit_post(self.owner, self.post))

    def test_editor_can_edit_own_published_post_but_not_another_users(self):
        self.add_membership(self.owner, BoardMembership.Role.EDITOR)
        self.add_membership(self.other, BoardMembership.Role.EDITOR)
        self.post.status = Post.STATUS_NORMAL
        self.post.save(update_fields=["status"])

        self.assertTrue(can_edit_post(self.owner, self.post))
        self.assertFalse(can_edit_post(self.other, self.post))
        self.assertFalse(can_review_post(self.owner, self.post))

    def test_reviewer_can_review_others_and_moderate_comments_but_not_edit(self):
        self.add_membership(self.other, BoardMembership.Role.REVIEWER)

        self.assertTrue(can_review_post(self.other, self.post))
        self.assertTrue(can_publish_post(self.other, self.post))
        self.assertTrue(can_moderate_comment(self.other, self.comment))
        self.assertFalse(can_edit_post(self.other, self.post))

    def test_reviewer_and_manager_cannot_review_their_own_post(self):
        for role in (BoardMembership.Role.REVIEWER, BoardMembership.Role.MANAGER):
            with self.subTest(role=role):
                BoardMembership.objects.update_or_create(
                    board=self.board,
                    user=self.owner,
                    defaults={"role": role, "is_active": True},
                )
                self.assertFalse(can_review_post(self.owner, self.post))
                self.assertFalse(can_publish_post(self.owner, self.post))

    def test_manager_can_manage_operational_settings_but_not_board_structure(self):
        self.add_membership(self.other, BoardMembership.Role.MANAGER)

        self.assertTrue(can_change_board_settings(self.other, self.board))
        self.assertTrue(can_manage_board_members(self.other, self.board))
        self.assertFalse(can_change_board_structure(self.other, self.board))
        self.assertFalse(can_create_board(self.other))
        self.assertFalse(can_delete_board(self.other, self.board))

    def test_inactive_user_membership_or_board_is_denied(self):
        membership = self.add_membership(
            self.owner,
            BoardMembership.Role.EDITOR,
            is_active=False,
        )
        self.assertIsNone(get_active_membership(self.owner, self.board))
        self.assertFalse(can_edit_post(self.owner, self.post))

        membership.is_active = True
        membership.save(update_fields=["is_active"])
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.assertFalse(can_edit_post(self.owner, self.post))

        self.owner.is_active = True
        self.owner.save(update_fields=["is_active"])
        self.board.is_active = False
        self.board.save(update_fields=["is_active"])
        self.assertFalse(can_edit_post(self.owner, self.post))

    def test_membership_and_direct_permission_cannot_expand_board_scope(self):
        other_category = Category.objects.create(name="Music", owner=self.owner)
        other_board = Board.objects.create(
            slug="music",
            name="Music",
            category=other_category,
        )
        other_post = Post.objects.create(
            title="Music Post",
            content="content",
            category=other_category,
            owner=self.owner,
        )
        self.add_membership(
            self.owner,
            BoardMembership.Role.EDITOR,
            board=other_board,
        )
        change_post = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Post),
            codename="change_post",
        )
        self.owner.user_permissions.add(change_post)

        self.assertFalse(can_edit_post(self.owner, self.post))
        self.assertTrue(can_edit_post(self.owner, other_post))

    def test_active_superuser_has_emergency_structural_and_object_access(self):
        superuser = MyUser.objects.create_superuser(
            email="root@example.com",
            username="root",
            password="test-password",
        )

        self.assertTrue(can_create_board(superuser))
        self.assertTrue(can_delete_board(superuser, self.board))
        self.assertTrue(can_change_board_structure(superuser, self.board))
        self.assertTrue(can_edit_post(superuser, self.post))
