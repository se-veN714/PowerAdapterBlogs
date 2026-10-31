from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from padif.models import Document, Version


class PadifWorkflowTests(TestCase):
    def setUp(self) -> None:
        User = get_user_model()
        self.member = User.objects.create_user(
            username="member",
            email="member@example.test",
            password="test-pass",
            is_active=True,
        )
        self.outsider = User.objects.create_user(
            username="outsider",
            email="outsider@example.test",
            password="test-pass",
            is_active=True,
        )
        call_command("bootstrap_padif_access", user=["member"], verbosity=0)

    def test_anonymous_user_is_redirected_to_host_login(self) -> None:
        response = self.client.get(reverse("padif:workspace"))
        self.assertRedirects(
            response,
            f"/accounts/login/?next={reverse('padif:workspace')}",
            fetch_redirect_response=False,
        )

    def test_authenticated_user_without_permission_gets_403(self) -> None:
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("padif:workspace"))
        self.assertEqual(response.status_code, 403)

    def test_group_member_can_upload_and_commit(self) -> None:
        self.client.force_login(self.member)
        upload = SimpleUploadedFile("handoff.md", "第一句。".encode(), "text/markdown")
        response = self.client.post(
            reverse("padif:workspace"),
            {"title": "交接稿", "markdown_file": upload, "commit_message": "初稿"},
        )
        document = Document.objects.get()
        self.assertRedirects(
            response,
            reverse("padif:document_detail", args=[document.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(document.current_version.semantic_version, "1.0.0")

        response = self.client.post(
            reverse("padif:commit_version", args=[document.pk]),
            {"content": "第一句。第二句。", "commit_message": "补充", "version_kind": "minor"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Version.objects.filter(document=document).count(), 2)
        self.assertEqual(document.versions.order_by("-id").first().semantic_version, "1.1.0")

    def test_cross_document_diff_is_rejected(self) -> None:
        self.client.force_login(self.member)
        documents = []
        for name in ("a.md", "b.md"):
            upload = SimpleUploadedFile(name, "正文。".encode(), "text/markdown")
            self.client.post(
                reverse("padif:workspace"),
                {"markdown_file": upload, "commit_message": "初稿"},
            )
            documents.append(Document.objects.order_by("-id").first())
        response = self.client.get(
            reverse("padif:diff_fragment", args=[documents[0].pk]),
            {"from_version": documents[0].current_version_id, "to_version": documents[1].current_version_id, "mode": "inline"},
        )
        self.assertEqual(response.status_code, 400)

    def test_existing_document_accepts_markdown_as_new_version(self) -> None:
        self.client.force_login(self.member)
        initial = SimpleUploadedFile("draft-v1.md", "第一版。".encode(), "text/markdown")
        self.client.post(
            reverse("padif:workspace"),
            {"markdown_file": initial, "commit_message": "初稿"},
        )
        document = Document.objects.get()
        next_file = SimpleUploadedFile(
            "draft-v2.md",
            "第一版。补充第二句。".encode(),
            "text/markdown",
        )
        response = self.client.post(
            reverse("padif:upload_version", args=[document.pk]),
            {
                "markdown_file": next_file,
                "commit_message": "朋友修订稿",
                "version_kind": "minor",
            },
        )
        self.assertRedirects(
            response,
            reverse("padif:document_detail", args=[document.pk]),
            fetch_redirect_response=False,
        )
        latest = document.versions.order_by("-id").first()
        self.assertEqual(latest.semantic_version, "1.1.0")
        self.assertEqual(latest.content, "第一版。补充第二句。")
        self.assertEqual(latest.created_by, self.member)

    def test_bootstrap_command_is_idempotent(self) -> None:
        call_command("bootstrap_padif_access", user=["member"], verbosity=0)
        group = Group.objects.get(name="PAdifUsers")
        permission = Permission.objects.get(codename="use_padif", content_type__app_label="padif")
        self.assertTrue(group.permissions.filter(pk=permission.pk).exists())
        self.assertEqual(self.member.groups.filter(pk=group.pk).count(), 1)
