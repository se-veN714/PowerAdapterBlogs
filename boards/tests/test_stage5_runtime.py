"""Cross-entry runtime contracts for accounts_linear stage 5."""

import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import MyUser
from Blogs.models import Category, Post, PostWorkflowEvent, Tag
from Blogs.revisions import create_revision
from Blogs.services import (
    approve_post,
    reject_post,
    submit_post_for_review,
    unpublish_post,
)
from boards.models import Board, BoardMembership


class Stage5RuntimePolicyTest(TestCase):
    def setUp(self):
        self.author = self.create_user("author")
        self.reviewer = self.create_user("reviewer")
        self.outsider = self.create_user("outsider", is_staff=True)
        self.category = Category.objects.create(name="Coding", owner=self.author)
        self.other_category = Category.objects.create(name="Music", owner=self.author)
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
        self.add_membership(self.author, self.board, BoardMembership.Role.EDITOR)
        self.add_membership(
            self.reviewer,
            self.board,
            BoardMembership.Role.REVIEWER,
        )

    @staticmethod
    def create_user(username, **extra_fields):
        return MyUser.objects.create_user(
            email=f"{username}@example.com",
            username=username,
            password="test-password",
            is_active=True,
            **extra_fields,
        )

    @staticmethod
    def add_membership(user, board, role):
        return BoardMembership.objects.create(board=board, user=user, role=role)

    def create_post(self, title, *, visibility=Post.VISIBILITY_PUBLIC, owner=None):
        return Post.objects.create(
            title=title,
            content="content",
            status=Post.STATUS_NORMAL,
            visibility=visibility,
            category=self.category,
            owner=owner or self.author,
        )

    def test_frontend_create_requires_membership_and_forces_draft(self):
        create_url = reverse("blogs:post_create")
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(create_url).status_code, 403)

        self.client.force_login(self.author)
        response = self.client.post(
            create_url,
            {
                "title": "New Draft",
                "desc": "draft description",
                "content": "draft body",
                "category": self.category.pk,
                "tag": [],
                "visibility": Post.VISIBILITY_PUBLIC,
                "change_type": "major",
                "edit_summary": "initial",
            },
        )

        post = Post.objects.get(title="New Draft")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(post.status, Post.STATUS_DRAFT)
        self.assertEqual(post.owner, self.author)
        self.assertFalse(post.cover)
        self.assertEqual(
            post.default_cover_static_path,
            "img/covers/default-code.webp",
        )
        self.assertEqual(
            response.url,
            reverse("blogs:post_detail", kwargs={"slug": post.slug}),
        )
        detail_response = self.client.get(response.url)
        self.assertContains(detail_response, "提交成功")
        self.assertContains(detail_response, "文章已保存为草稿")
        self.assertContains(detail_response, "作者预览")
        self.assertContains(detail_response, "class=\"meta-edit\"")

    def test_prepublication_detail_and_revision_are_author_only(self):
        post = self.create_post("Author preview")
        post.status = Post.STATUS_REVIEW
        post.save(update_fields=["status"])
        revision = create_revision(post, self.author, change_type="major")
        detail_url = reverse("blogs:post_detail", kwargs={"slug": post.slug})
        revision_url = reverse(
            "blogs:revision_body",
            kwargs={"slug": post.slug, "version": revision.version},
        )

        self.client.force_login(self.author)
        author_detail = self.client.get(detail_url)
        self.assertEqual(author_detail.status_code, 200)
        self.assertContains(author_detail, "审核中 · 作者预览")
        self.assertContains(author_detail, "class=\"meta-edit\"")
        self.assertEqual(
            self.client.get(revision_url, HTTP_HX_REQUEST="true").status_code,
            200,
        )
        post.refresh_from_db()
        self.assertEqual(post.pv, 0)

        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.assertEqual(
            self.client.get(revision_url, HTTP_HX_REQUEST="true").status_code,
            404,
        )

        self.client.logout()
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_published_detail_edit_button_follows_edit_policy(self):
        post = self.create_post("Published edit link")
        detail_url = reverse("blogs:post_detail", kwargs={"slug": post.slug})

        self.client.force_login(self.author)
        self.assertContains(self.client.get(detail_url), "class=\"meta-edit\"")

        self.client.force_login(self.reviewer)
        self.assertNotContains(self.client.get(detail_url), "class=\"meta-edit\"")

    def test_published_navigation_does_not_leak_draft_title(self):
        published = self.create_post("Visible published article")
        draft = self.create_post("SECRET DRAFT TITLE")
        draft.status = Post.STATUS_DRAFT
        draft.save(update_fields=["status"])

        self.client.logout()
        response = self.client.get(
            reverse("blogs:post_detail", kwargs={"slug": published.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, draft.title)

    def test_post_form_renders_localized_visibility_and_category_cover_fallback(self):
        self.client.force_login(self.author)

        response = self.client.get(reverse("blogs:post_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "可见性")
        self.assertContains(response, "仅本板块成员可见")
        self.assertContains(response, "category-cover-map")
        self.assertContains(response, "/static/img/covers/default-code.webp")
        self.assertContains(response, "未上传自定义封面，将根据分类自动使用默认封面")
        self.assertNotContains(response, "预设封面")
        self.assertNotContains(response, "cover-preset")

    def test_missing_visibility_uses_localized_field_error(self):
        self.client.force_login(self.author)

        response = self.client.post(
            reverse("blogs:post_create"),
            {
                "title": "Missing visibility",
                "desc": "description",
                "content": "body",
                "category": self.category.pk,
                "tag": [],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "可见性")
        self.assertContains(response, "请选择文章可见性。")
        self.assertNotContains(response, "<li>visibility", html=False)
        self.assertFalse(Post.objects.filter(title="Missing visibility").exists())

    def test_unknown_category_uses_generic_default_cover(self):
        category = Category.objects.create(name="随笔", owner=self.author)
        post = Post.objects.create(
            title="Generic cover",
            content="body",
            category=category,
            owner=self.author,
        )

        self.assertFalse(post.cover)
        self.assertEqual(post.default_cover_static_path, "img/Cover.png")

    def test_frontend_form_rejects_category_outside_membership(self):
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("blogs:post_create"),
            {
                "title": "Cross Board",
                "desc": "draft description",
                "content": "draft body",
                "category": self.other_category.pk,
                "tag": [],
                "visibility": Post.VISIBILITY_PUBLIC,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("category", response.context["form"].errors)
        self.assertFalse(Post.objects.filter(title="Cross Board").exists())

    def test_editor_edit_of_published_post_preserves_owner_and_returns_to_draft(self):
        post = self.create_post("Published")
        self.client.force_login(self.author)

        response = self.client.post(
            reverse("blogs:post_edit", kwargs={"slug": post.slug}),
            {
                "title": "Edited Published",
                "desc": "updated description",
                "content": "updated body",
                "category": self.category.pk,
                "tag": [],
                "visibility": Post.VISIBILITY_PUBLIC,
                "change_type": "minor",
                "edit_summary": "edit",
            },
        )

        post.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(post.status, Post.STATUS_DRAFT)
        self.assertEqual(post.owner, self.author)
        self.assertEqual(post.revisions.count(), 1)
        event = post.workflow_events.get()
        self.assertEqual(
            event.event_type,
            PostWorkflowEvent.EventType.RETURNED_TO_DRAFT,
        )
        self.assertEqual(event.from_status, Post.STATUS_NORMAL)
        self.assertEqual(event.to_status, Post.STATUS_DRAFT)
        self.assertEqual(event.revision, post.revisions.get())
        self.assertEqual(event.actor, self.author)
        self.assertEqual(
            response.url,
            reverse("blogs:post_detail", kwargs={"slug": post.slug}),
        )
        self.assertContains(self.client.get(response.url), "保存成功。")

    def test_frontend_edit_rejects_stale_revision_without_overwriting(self):
        post = self.create_post("Concurrent draft")
        post.status = Post.STATUS_DRAFT
        post.save(update_fields=["status"])
        initial = create_revision(post, self.author, change_type="major")
        self.client.force_login(self.author)

        edit_url = reverse("blogs:post_edit", kwargs={"slug": post.slug})
        edit_page = self.client.get(edit_url)
        self.assertEqual(
            edit_page.context["form"]["base_revision_id"].value(),
            initial.pk,
        )

        post.content = "A competing edit"
        post.save(update_fields=["content"])
        create_revision(post, self.author, change_type="minor")

        response = self.client.post(
            edit_url,
            {
                "title": "Stale title",
                "desc": "stale description",
                "content": "Stale content",
                "category": self.category.pk,
                "tag": [],
                "visibility": Post.VISIBILITY_PUBLIC,
                "change_type": "minor",
                "edit_summary": "stale edit",
                "base_revision_id": initial.pk,
            },
        )

        post.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "文章在你打开编辑页后已产生新版本")
        self.assertEqual(post.title, "Concurrent draft")
        self.assertEqual(post.content, "A competing edit")
        self.assertEqual(post.revisions.count(), 2)

    def test_frontend_edit_rolls_back_post_when_revision_creation_fails(self):
        post = self.create_post("Atomic draft")
        post.status = Post.STATUS_DRAFT
        post.save(update_fields=["status"])
        initial = create_revision(post, self.author, change_type="major")
        self.client.force_login(self.author)

        with patch("Blogs.services.create_revision", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("blogs:post_edit", kwargs={"slug": post.slug}),
                    {
                        "title": "Must roll back",
                        "desc": "updated description",
                        "content": "updated body",
                        "category": self.category.pk,
                        "tag": [],
                        "visibility": Post.VISIBILITY_PUBLIC,
                        "change_type": "minor",
                        "edit_summary": "atomicity test",
                        "base_revision_id": initial.pk,
                    },
                )

        post.refresh_from_db()
        self.assertEqual(post.title, "Atomic draft")
        self.assertEqual(post.content, "content")
        self.assertEqual(post.revisions.count(), 1)

    def test_staff_flag_does_not_bypass_staff_only_board_scope(self):
        post = self.create_post(
            "Internal",
            visibility=Post.VISIBILITY_STAFF_ONLY,
        )
        detail_url = reverse("blogs:post_detail", kwargs={"slug": post.slug})

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(detail_url).status_code, 404)

        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(detail_url).status_code, 200)

    def test_upload_requires_post_creation_membership(self):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        upload_url = reverse("blogs:post_img_upload")

        self.client.force_login(self.outsider)
        denied_image = SimpleUploadedFile("denied.png", png, content_type="image/png")
        self.assertEqual(
            self.client.post(upload_url, {"image": denied_image}).status_code,
            403,
        )

        self.client.force_login(self.author)
        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            allowed_image = SimpleUploadedFile(
                "allowed.png",
                png,
                content_type="image/png",
            )
            response = self.client.post(upload_url, {"image": allowed_image})
            self.assertEqual(response.status_code, 200)
            stored_name = response.json()["url"].rsplit("/", 1)[-1]
            self.assertTrue(Path(media_root, "post_images", stored_name).exists())

    def test_workflow_service_enforces_role_state_and_self_review(self):
        post = self.create_post("Workflow")
        post.status = Post.STATUS_DRAFT
        post.save(update_fields=["status"])
        revision = create_revision(post, self.author, change_type="major")

        submitted = submit_post_for_review(post=post, user=self.author)
        self.assertEqual(submitted.status, Post.STATUS_REVIEW)
        submitted_event = post.workflow_events.get(
            event_type=PostWorkflowEvent.EventType.SUBMITTED,
        )
        self.assertEqual(submitted_event.from_status, Post.STATUS_DRAFT)
        self.assertEqual(submitted_event.to_status, Post.STATUS_REVIEW)
        self.assertEqual(submitted_event.actor, self.author)
        self.assertEqual(submitted_event.revision, revision)

        published = approve_post(post=submitted, user=self.reviewer)
        self.assertEqual(published.status, Post.STATUS_NORMAL)
        approved_event = post.workflow_events.get(
            event_type=PostWorkflowEvent.EventType.APPROVED,
        )
        self.assertEqual(approved_event.from_status, Post.STATUS_REVIEW)
        self.assertEqual(approved_event.to_status, Post.STATUS_NORMAL)
        self.assertEqual(approved_event.actor, self.reviewer)
        self.assertEqual(approved_event.revision, revision)
        self.assertEqual(post.revisions.count(), 1)

        unpublished = unpublish_post(post=published, user=self.reviewer)
        self.assertEqual(unpublished.status, Post.STATUS_DELETE)
        self.assertTrue(
            post.workflow_events.filter(
                event_type=PostWorkflowEvent.EventType.UNPUBLISHED,
                from_status=Post.STATUS_NORMAL,
                to_status=Post.STATUS_DELETE,
                revision=revision,
            ).exists()
        )

        own_review = self.create_post("Reviewer Own", owner=self.reviewer)
        own_review.status = Post.STATUS_REVIEW
        own_review.save(update_fields=["status"])
        with self.assertRaises(PermissionDenied):
            approve_post(post=own_review, user=self.reviewer)
        self.assertFalse(own_review.workflow_events.exists())

    def test_review_workspace_exposes_only_valid_scoped_transitions(self):
        draft = self.create_post("Author draft")
        draft.status = Post.STATUS_DRAFT
        draft.save(update_fields=["status"])
        review = self.create_post("Awaiting review")
        review.status = Post.STATUS_REVIEW
        review.save(update_fields=["status"])
        published = self.create_post("Published article")
        url = reverse("blogs:review_workspace")

        self.client.force_login(self.author)
        author_page = self.client.get(url)
        self.assertContains(author_page, draft.title)
        self.assertNotContains(author_page, review.title)

        self.client.force_login(self.reviewer)
        reviewer_page = self.client.get(url)
        self.assertNotContains(reviewer_page, draft.title)
        self.assertContains(reviewer_page, review.title)
        self.assertContains(reviewer_page, published.title)
        self.assertContains(reviewer_page, "通过并发布")
        self.assertContains(reviewer_page, "驳回为草稿")
        self.assertContains(reviewer_page, "下架文章")

        approved = self.client.post(
            url,
            {"post_id": review.pk, "workflow_action": "approve"},
        )
        self.assertRedirects(approved, url)
        review.refresh_from_db()
        self.assertEqual(review.status, Post.STATUS_NORMAL)

        invalid = self.client.post(
            url,
            {"post_id": published.pk, "workflow_action": "reject"},
            follow=True,
        )
        self.assertContains(invalid, "只有审核中的文章可以驳回为草稿")
        published.refresh_from_db()
        self.assertEqual(published.status, Post.STATUS_NORMAL)

    def test_review_workspace_rejects_user_without_board_role(self):
        self.client.force_login(self.outsider)
        self.assertEqual(
            self.client.get(reverse("blogs:review_workspace")).status_code,
            403,
        )

    def test_published_workspace_filters_and_uses_cursor_lazy_loading(self):
        tag = Tag.objects.create(name="Release", owner=self.author)
        posts = [self.create_post(f"Published {index:02d}") for index in range(11)]
        target = posts[-1]
        target.title = "Published needle"
        target.desc = "filter target"
        target.save(update_fields=["title", "desc"])
        target.tag.add(tag)
        other_board_post = Post.objects.create(
            title="Music published",
            content="content",
            status=Post.STATUS_NORMAL,
            visibility=Post.VISIBILITY_PUBLIC,
            category=self.other_category,
            owner=self.author,
        )
        self.add_membership(
            self.reviewer,
            self.other_board,
            BoardMembership.Role.REVIEWER,
        )
        url = reverse("blogs:review_workspace")
        self.client.force_login(self.reviewer)

        first_page = self.client.get(url)
        self.assertContains(first_page, "按板块筛选")
        self.assertContains(first_page, "加载更多")
        self.assertContains(first_page, target.title)
        self.assertNotContains(first_page, posts[0].title)
        next_url = first_page.context["published_next_url"]

        with CaptureQueriesContext(connection) as queries:
            next_page = self.client.get(next_url, HTTP_HX_REQUEST="true")
        self.assertEqual(next_page.status_code, 200)
        self.assertNotContains(next_page, "MY DRAFTS")
        self.assertContains(next_page, posts[0].title)
        self.assertFalse(
            any(
                query["sql"].lstrip().upper().startswith("SELECT COUNT(")
                for query in queries.captured_queries
            )
        )

        filtered = self.client.get(
            url,
            {
                "section": "published",
                "board": self.board.slug,
                "tag": tag.pk,
                "author": self.author.pk,
                "q": "needle",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(filtered, target.title)
        self.assertNotContains(filtered, other_board_post.title)
        self.assertNotContains(filtered, posts[0].title)

    def test_reject_records_event_without_creating_content_revision(self):
        post = self.create_post("Rejected workflow")
        post.status = Post.STATUS_DRAFT
        post.save(update_fields=["status"])
        revision = create_revision(post, self.author, change_type="major")

        submitted = submit_post_for_review(post=post, user=self.author)
        rejected = reject_post(post=submitted, user=self.reviewer)

        self.assertEqual(rejected.status, Post.STATUS_DRAFT)
        event = post.workflow_events.get(
            event_type=PostWorkflowEvent.EventType.REJECTED,
        )
        self.assertEqual(event.from_status, Post.STATUS_REVIEW)
        self.assertEqual(event.to_status, Post.STATUS_DRAFT)
        self.assertEqual(event.revision, revision)
        self.assertEqual(post.revisions.count(), 1)

    def test_workflow_status_rolls_back_when_event_cannot_be_recorded(self):
        post = self.create_post("Atomic workflow")
        post.status = Post.STATUS_DRAFT
        post.save(update_fields=["status"])

        with patch(
            "Blogs.services.PostWorkflowEvent.objects.create",
            side_effect=RuntimeError("event write failed"),
        ):
            with self.assertRaises(RuntimeError):
                submit_post_for_review(post=post, user=self.author)

        post.refresh_from_db()
        self.assertEqual(post.status, Post.STATUS_DRAFT)
        self.assertFalse(post.workflow_events.exists())

    def test_api_is_read_only_and_scopes_internal_posts(self):
        public_post = self.create_post("Public")
        internal_post = self.create_post(
            "Internal API",
            visibility=Post.VISIBILITY_STAFF_ONLY,
        )
        list_url = reverse("blogs:Blogs:api_post-list")

        anonymous_response = self.client.get(list_url)
        anonymous_ids = {item["id"] for item in anonymous_response.json()["results"]}
        self.assertIn(public_post.pk, anonymous_ids)
        self.assertNotIn(internal_post.pk, anonymous_ids)

        self.client.force_login(self.reviewer)
        reviewer_response = self.client.get(list_url)
        reviewer_ids = {item["id"] for item in reviewer_response.json()["results"]}
        self.assertIn(public_post.pk, reviewer_ids)
        self.assertIn(internal_post.pk, reviewer_ids)
        self.assertEqual(self.client.post(list_url, {}).status_code, 405)
