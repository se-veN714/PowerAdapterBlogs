from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from padif.models import Annotation, AnnotationReply, DocumentCollaborator
from padif.services import archive_branch, commit_document_version, create_branch, effective_head
from padif.tests.test_branching import make_document


class BranchAdoptionTests(TestCase):
    def setUp(self):
        self.owner = self.make_user("adoption-owner")
        self.client.force_login(self.owner)
        self.document = make_document(self.owner)
        self.main = self.document.current_version
        self.blog = self.create_branch("blog-line")
        self.video = self.create_branch("video-line")
        self.source = self.commit(self.blog, "# Blog\n\nOlder source draft.\n")
        self.blog_head = self.commit(self.blog, "# Blog\n\nNewer source draft.")
        self.target = self.commit(self.video, "# Video\n\nOriginal target draft.")
        self.url = reverse("padif:adopt_version", args=[self.document.pk, self.video.pk])
        self.payload = {"source_version_id": self.source.pk, "base_version_id": self.target.pk,
                        "commit_message": "Adopt blog draft", "version_kind": "minor", "confirm_replace": "on"}

    def make_user(self, name):
        user = get_user_model().objects.create_user(username=name, email=f"{name}@example.test",
                                                     password="test-pass", is_active=True)
        user.user_permissions.add(Permission.objects.get(codename="use_padif"))
        return user

    def create_branch(self, name):
        return create_branch(document_id=self.document.pk, user=self.owner, name=name,
                             fork_from_version_id=self.main.pk)

    def commit(self, branch, content):
        return commit_document_version(document_id=self.document.pk, user=self.owner, branch_id=branch.pk,
                                       base_version_id=effective_head(branch).pk, content=content,
                                       commit_message="Revision", version_kind="patch").version

    def test_review_and_adopt_historical_source_preserves_versions_and_notes(self):
        notes = [Annotation.objects.create(version=version, author=self.owner, kind="question",
                                           body="Existing note", start_line=1, end_line=1)
                 for version in (self.source, self.target)]
        reply = AnnotationReply.objects.create(annotation=notes[1], author=self.owner, body="Existing reply")
        detail = reverse("padif:document_detail", args=[self.document.pk])
        self.assertContains(self.client.get(detail, {"branch": "video-line"}), self.url)
        picker = self.client.get(self.url)
        self.assertContains(picker, "比较版本")
        self.assertNotContains(picker, "确认采用为新版本")
        review = self.client.get(self.url, {"source_version": self.source.pk})
        self.assertContains(review, "目标当前版 → 来源整稿")
        self.assertContains(review, 'class="inline-view"')
        self.assertEqual(review.context["diff"]["old"], self.target)
        self.assertEqual(review.context["diff"]["new"], self.source)
        before = self.document.versions.count()
        self.assertRedirects(self.client.post(self.url, self.payload), detail + "?branch=video-line")
        version = effective_head(self.video)
        self.assertEqual(version.parent, self.target)
        self.assertEqual(version.adopted_from, self.source)
        self.assertEqual(version.content, self.source.content)
        self.assertEqual(version.semantic_version, "1.1.0")
        self.assertEqual(effective_head(self.blog), self.blog_head)
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version, self.main)
        self.assertEqual(self.document.versions.count(), before + 1)
        self.assertFalse(version.annotations.exists())
        self.assertEqual(set(Annotation.objects.values_list("pk", "version_id")),
                         {(note.pk, note.version_id) for note in notes})
        reply.refresh_from_db()
        self.assertEqual(reply.annotation_id, notes[1].pk)
        self.assertContains(self.client.get(detail, {"branch": "video-line"}), "采用自")

    def test_stale_target_rejects_and_recompare_retains_the_pinned_source(self):
        self.client.get(self.url, {"source_version": self.source.pk})
        updated = self.commit(self.video, "Concurrent target change.")
        response = self.client.post(self.url, self.payload)
        self.assertContains(response, "目标分支已更新", status_code=409)
        self.assertNotContains(response, "确认采用为新版本", status_code=409)
        self.assertEqual(effective_head(self.video), updated)
        review = self.client.get(self.url + response.context["review_again"])
        self.assertEqual(review.context["diff"]["old"], updated)
        self.assertEqual(review.context["diff"]["new"], self.source)
        self.assertEqual(self.client.post(self.url, {**self.payload, "base_version_id": updated.pk}).status_code, 302)
        self.assertEqual(effective_head(self.video).parent, updated)

    def test_invalid_sources_and_missing_confirmation_leave_target_alone(self):
        foreign = make_document(self.owner).current_version
        for source in (self.target, foreign):
            with self.subTest(source=source.pk):
                self.assertEqual(self.client.get(self.url, {"source_version": source.pk}).status_code, 400)
                self.assertEqual(self.client.post(self.url, {**self.payload, "source_version_id": source.pk}).status_code, 400)
        self.assertEqual(self.client.post(self.url, {**self.payload, "confirm_replace": ""}).status_code, 400)
        self.assertEqual(effective_head(self.video), self.target)

    def test_viewer_cannot_adopt_and_collaborator_can_adopt_non_main(self):
        member = self.make_user("adoption-member")
        membership = DocumentCollaborator.objects.create(document=self.document, user=member,
                                                          granted_by=self.owner, role="viewer")
        self.client.force_login(member)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.payload).status_code, 403)
        membership.role = "collaborator"
        membership.save(update_fields=["role"])
        self.assertEqual(self.client.post(self.url, self.payload).status_code, 302)

    def test_main_and_archived_target_are_rejected(self):
        main_url = reverse("padif:adopt_version", args=[self.document.pk, self.main.branch_id])
        self.assertEqual(self.client.post(main_url, {**self.payload, "base_version_id": self.main.pk}).status_code, 400)
        archive_branch(document_id=self.document.pk, user=self.owner, branch_id=self.video.pk)
        self.assertEqual(self.client.post(self.url, self.payload).status_code, 409)
        self.assertEqual(effective_head(self.video), self.target)

    def test_dialog_returns_fragment_on_review_and_conflict_and_destination_on_success(self):
        headers = {"HTTP_X_PADIF_ADOPT_DIALOG": "1"}
        review = self.client.get(self.url, {"source_version": self.source.pk}, **headers)
        self.assertTemplateUsed(review, "padif/_branch_adopt_form.html")
        self.assertNotContains(review, "<!doctype")
        updated = self.commit(self.video, "Concurrent dialog change.")
        conflict = self.client.post(self.url, self.payload, **headers)
        self.assertEqual(conflict.headers["X-PAdif-Adopt-Dialog"], "1")
        self.assertContains(conflict, "重新比较后确认", status_code=409)
        self.assertNotContains(conflict, "确认采用为新版本", status_code=409)
        success = self.client.post(self.url, {**self.payload, "base_version_id": updated.pk}, **headers)
        self.assertEqual(success.json()["url"],
                         reverse("padif:document_detail", args=[self.document.pk]) + "?branch=video-line")
        self.assertEqual(effective_head(self.video).adopted_from, self.source)
