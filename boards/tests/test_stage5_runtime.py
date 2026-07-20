"""Cross-entry runtime contracts for accounts_linear stage 5."""

import base64
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import MyUser
from Blogs.models import Category, Post
from Blogs.services import approve_post, submit_post_for_review
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
        self.assertEqual(
            response.url,
            reverse("blogs:post_edit", kwargs={"slug": post.slug}),
        )

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
        self.assertEqual(
            response.url,
            reverse("blogs:post_edit", kwargs={"slug": post.slug}),
        )

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

        submitted = submit_post_for_review(post=post, user=self.author)
        self.assertEqual(submitted.status, Post.STATUS_REVIEW)

        published = approve_post(post=submitted, user=self.reviewer)
        self.assertEqual(published.status, Post.STATUS_NORMAL)

        own_review = self.create_post("Reviewer Own", owner=self.reviewer)
        own_review.status = Post.STATUS_REVIEW
        own_review.save(update_fields=["status"])
        with self.assertRaises(PermissionDenied):
            approve_post(post=own_review, user=self.reviewer)

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
