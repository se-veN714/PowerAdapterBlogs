import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.agent_auth import (
    AGENT_SCOPE_PADIF_ANNOTATE,
    AGENT_SCOPE_PADIF_READ,
    AGENT_SCOPE_PADIF_VERSION,
    authenticate_agent_token,
    approve_device_authorization,
    create_device_authorization,
    issue_access_token,
    revoke_agent_access_token,
)
from accounts.models import AgentAccessToken, AgentDeviceAuthorization
from padif.models import Document, Version
from security.models import AuditOutbox


class AgentAuthorizationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="agent-owner",
            email="agent-owner@example.test",
            password="test-password",
        )

    def test_device_authorization_issues_scoped_token_and_can_revoke(self):
        start = self.client.post(
            reverse("accounts:agent-device-start"),
            data=json.dumps(
                {"client_name": "Writing Agent", "scopes": [AGENT_SCOPE_PADIF_READ]}
            ),
            content_type="application/json",
        )
        self.assertEqual(start.status_code, 200)
        device = start.json()
        self.assertIn("device_code", device)
        self.assertIn("user_code", device)

        pending = self.client.post(
            reverse("accounts:agent-device-token"),
            data=json.dumps({"device_code": device["device_code"]}),
            content_type="application/json",
        )
        self.assertEqual(pending.status_code, 400)
        self.assertEqual(pending.json()["error"], "authorization_pending")
        self.assertEqual(pending.json()["interval"], 5)

        self.client.force_login(self.user)
        authorize_url = f'{reverse("accounts:agent-authorize")}?user_code={device["user_code"]}'
        self.assertEqual(self.client.get(authorize_url).status_code, 200)
        approved = self.client.post(
            reverse("accounts:agent-authorize"),
            {"user_code": device["user_code"], "action": "approve"},
        )
        self.assertEqual(approved.status_code, 200)

        issued = self.client.post(
            reverse("accounts:agent-device-token"),
            data=json.dumps({"device_code": device["device_code"]}),
            content_type="application/json",
        )
        self.assertEqual(issued.status_code, 200)
        access_token = issued.json()["access_token"]
        token = AgentAccessToken.objects.get()
        authenticated, error = authenticate_agent_token(
            access_token,
            required_scope=AGENT_SCOPE_PADIF_READ,
        )
        self.assertIsNone(error)
        self.assertEqual(authenticated.user_id, self.user.pk)

        revoked = self.client.post(
            reverse("accounts:agent-token-revoke", args=[token.pk])
        )
        self.assertEqual(revoked.status_code, 200)
        authenticated, error = authenticate_agent_token(access_token)
        self.assertIsNone(authenticated)
        self.assertEqual(error, "invalid_token")
        self.assertEqual(
            set(AuditOutbox.objects.values_list("event_type", flat=True)),
            {
                "agent.authorization.requested",
                "agent.authorization.approved",
                "agent.token.issued",
                "agent.token.revoked",
            },
        )

    def test_unknown_scope_is_rejected(self):
        response = self.client.post(
            reverse("accounts:agent-device-start"),
            data=json.dumps({"client_name": "Agent", "scopes": ["admin:all"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "unsupported_scope")

    def test_empty_scope_list_is_rejected(self):
        response = self.client.post(
            reverse("accounts:agent-device-start"),
            data=json.dumps({"client_name": "Agent", "scopes": []}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "unsupported_scope")

    def test_bearer_token_can_read_padif_workspace(self):
        document = Document.objects.create(title="Agent document", created_by=self.user)
        version = Version.objects.create(
            document=document,
            content="# Draft",
            commit_message="Initial",
            semantic_version="1.0.0",
            version_kind=Version.Kind.MAJOR,
            created_by=self.user,
        )
        document.current_version = version
        document.save(update_fields=("current_version",))
        device = create_device_authorization(
            client_name="Reading Agent",
            scopes=[AGENT_SCOPE_PADIF_READ],
        )
        approve_device_authorization(
            user=self.user,
            user_code=device["user_code"],
            approve=True,
        )
        issued = issue_access_token(
            authorization=device["authorization"],
            device_code=device["device_code"],
        )
        response = self.client.get(
            reverse("padif:agent-workspace", args=[document.pk]),
            HTTP_AUTHORIZATION=f"Bearer {issued['access_token']}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_version"]["content"], "# Draft")

    def test_scoped_bearer_token_can_write_annotation_reply_and_version(self):
        document = Document.objects.create(title="Agent writable", created_by=self.user)
        version = Version.objects.create(
            document=document,
            content="第一句。",
            commit_message="Initial",
            semantic_version="1.0.0",
            version_kind=Version.Kind.MAJOR,
            created_by=self.user,
        )
        document.current_version = version
        document.save(update_fields=("current_version",))
        scopes = [AGENT_SCOPE_PADIF_READ, AGENT_SCOPE_PADIF_ANNOTATE, AGENT_SCOPE_PADIF_VERSION]
        device = create_device_authorization(client_name="Writing Agent", scopes=scopes)
        approve_device_authorization(user=self.user, user_code=device["user_code"], approve=True)
        issued = issue_access_token(authorization=device["authorization"], device_code=device["device_code"])
        headers = {"HTTP_AUTHORIZATION": f"Bearer {issued['access_token']}"}

        annotation_response = self.client.post(
            reverse("padif:agent-create-annotation", args=[version.pk]),
            data=json.dumps(
                {
                    "kind": "suggestion",
                    "body": "请补充上下文。",
                    "start_line": 1,
                    "end_line": 1,
                    "selected_text": "第一句。",
                }
            ),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(annotation_response.status_code, 201)
        annotation_id = annotation_response.json()["annotation"]["id"]
        reply_response = self.client.post(
            reverse("padif:agent-create-reply", args=[annotation_id]),
            data=json.dumps({"body": "下一版会补上。"}),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(reply_response.status_code, 201)
        version_response = self.client.post(
            reverse("padif:agent-commit-version", args=[document.pk]),
            data=json.dumps(
                {
                    "base_version_id": version.pk,
                    "content": "第一句。补充第二句。",
                    "commit_message": "Agent revision",
                    "version_kind": "patch",
                }
            ),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(version_response.status_code, 201)

    def test_agent_can_discover_documents_read_diff_and_resolve_annotation(self):
        document = Document.objects.create(title="Agent discovery", created_by=self.user)
        first = Version.objects.create(
            document=document,
            content="第一句。\n\n第二句。",
            commit_message="Initial",
            semantic_version="1.0.0",
            version_kind=Version.Kind.MAJOR,
            created_by=self.user,
        )
        second = Version.objects.create(
            document=document,
            content="第一句。\n\n第二句已修改。",
            commit_message="Revision",
            semantic_version="1.1.0",
            version_kind=Version.Kind.MINOR,
            created_by=self.user,
        )
        document.current_version = second
        document.save(update_fields=("current_version",))
        device = create_device_authorization(
            client_name="Discovery Agent",
            scopes=[AGENT_SCOPE_PADIF_READ, AGENT_SCOPE_PADIF_ANNOTATE],
        )
        approve_device_authorization(user=self.user, user_code=device["user_code"], approve=True)
        issued = issue_access_token(
            authorization=device["authorization"],
            device_code=device["device_code"],
        )
        headers = {"HTTP_AUTHORIZATION": f"Bearer {issued['access_token']}"}

        capabilities = self.client.get(reverse("padif:agent-capabilities"))
        self.assertEqual(capabilities.status_code, 200)
        self.assertIn("/padif/api/documents/{document_id}/diff/", capabilities.json()["resources"]["diff"])

        listing = self.client.get(reverse("padif:agent-documents"), **headers)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["documents"][0]["id"], document.pk)

        diff = self.client.get(
            reverse("padif:agent-diff", args=[document.pk]),
            {"from_version": first.pk, "to_version": second.pk},
            **headers,
        )
        self.assertEqual(diff.status_code, 200)
        self.assertEqual(diff.json()["diff"]["stats"]["chars_added"], 3)
        self.assertEqual(diff.json()["diff"]["ops"][1]["new_line"], 3)

        from padif.models import Annotation

        annotation = Annotation.objects.create(
            version=second,
            author=self.user,
            kind=Annotation.Kind.SUGGESTION,
            body="请确认这处修改。",
            start_line=3,
            end_line=3,
        )
        invalid = self.client.patch(
            reverse("padif:agent-update-annotation", args=[annotation.pk]),
            data=json.dumps({"status": "resolved", "resolution_note": ""}),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()["error"], "RESOLUTION_NOTE_REQUIRED")
        resolved = self.client.patch(
            reverse("padif:agent-update-annotation", args=[annotation.pk]),
            data=json.dumps({"status": "resolved", "resolution_note": "已核对并采纳。"}),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["annotation"]["status"], "resolved")

    @override_settings(AGENT_DEVICE_START_RATE_LIMIT=1, AGENT_DEVICE_START_RATE_WINDOW=120)
    def test_device_start_is_rate_limited_per_client(self):
        cache.clear()
        first = self.client.post(
            reverse("accounts:agent-device-start"),
            data=json.dumps({"client_name": "Rate limited Agent"}),
            content_type="application/json",
        )
        second = self.client.post(
            reverse("accounts:agent-device-start"),
            data=json.dumps({"client_name": "Rate limited Agent"}),
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second["Retry-After"], "120")
        self.assertEqual(second.json()["error"], "rate_limited")
        self.assertEqual(AgentDeviceAuthorization.objects.count(), 1)

    def test_agent_token_management_page_lists_and_revokes_only_own_tokens(self):
        authorization = AgentDeviceAuthorization.objects.create(
            client_name="Writing Agent",
            device_code_digest="a" * 64,
            user_code_digest="b" * 64,
            scopes=[AGENT_SCOPE_PADIF_READ, AGENT_SCOPE_PADIF_ANNOTATE],
            user=self.user,
            status=AgentDeviceAuthorization.Status.CONSUMED,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        token = AgentAccessToken.objects.create(
            authorization=authorization,
            user=self.user,
            token_digest="c" * 64,
            scopes=authorization.scopes,
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:agent-token-management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Writing Agent")
        self.assertContains(response, "padif:annotate")
        self.assertContains(response, "cccccccc")
        self.assertNotContains(response, "c" * 64)

        revoked = self.client.post(
            reverse("accounts:agent-token-management"),
            {"token_id": token.pk},
        )
        self.assertRedirects(
            revoked,
            reverse("accounts:agent-token-management"),
            fetch_redirect_response=False,
        )
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)

        other_user = get_user_model().objects.create_user(
            username="other-agent-owner",
            email="other-agent-owner@example.test",
            password="test-password",
        )
        other_authorization = AgentDeviceAuthorization.objects.create(
            client_name="Other Agent",
            device_code_digest="i" * 64,
            user_code_digest="j" * 64,
            scopes=[AGENT_SCOPE_PADIF_READ],
            user=other_user,
            status=AgentDeviceAuthorization.Status.CONSUMED,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        other_token = AgentAccessToken.objects.create(
            authorization=other_authorization,
            user=other_user,
            token_digest="k" * 64,
            scopes=[AGENT_SCOPE_PADIF_READ],
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        self.client.post(
            reverse("accounts:agent-token-management"),
            {"token_id": other_token.pk},
        )
        other_token.refresh_from_db()
        self.assertIsNone(other_token.revoked_at)

    def test_cleanup_agent_authorizations_preserves_live_consumed_token(self):
        now = timezone.now()
        pending = AgentDeviceAuthorization.objects.create(
            client_name="Expired Pending",
            device_code_digest="d" * 64,
            user_code_digest="e" * 64,
            scopes=[AGENT_SCOPE_PADIF_READ],
            expires_at=now - timedelta(minutes=1),
        )
        live_authorization = AgentDeviceAuthorization.objects.create(
            client_name="Live Consumed",
            device_code_digest="f" * 64,
            user_code_digest="g" * 64,
            scopes=[AGENT_SCOPE_PADIF_READ],
            user=self.user,
            status=AgentDeviceAuthorization.Status.CONSUMED,
            expires_at=now - timedelta(minutes=1),
        )
        live_token = AgentAccessToken.objects.create(
            authorization=live_authorization,
            user=self.user,
            token_digest="h" * 64,
            scopes=[AGENT_SCOPE_PADIF_READ],
            expires_at=now + timedelta(minutes=10),
        )
        call_command("cleanup_agent_authorizations", dry_run=True)
        self.assertTrue(AgentDeviceAuthorization.objects.filter(pk=pending.pk).exists())
        call_command("cleanup_agent_authorizations")
        self.assertFalse(AgentDeviceAuthorization.objects.filter(pk=pending.pk).exists())
        self.assertTrue(AgentDeviceAuthorization.objects.filter(pk=live_authorization.pk).exists())
        self.assertTrue(AgentAccessToken.objects.filter(pk=live_token.pk).exists())

    def test_admin_revoke_service_records_admin_audit_event(self):
        authorization = AgentDeviceAuthorization.objects.create(
            client_name="Admin Agent",
            device_code_digest="l" * 64,
            user_code_digest="m" * 64,
            scopes=[AGENT_SCOPE_PADIF_READ],
            user=self.user,
            status=AgentDeviceAuthorization.Status.CONSUMED,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        token = AgentAccessToken.objects.create(
            authorization=authorization,
            user=self.user,
            token_digest="n" * 64,
            scopes=[AGENT_SCOPE_PADIF_READ],
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        self.assertTrue(
            revoke_agent_access_token(
                token_id=token.pk,
                actor=self.user,
                source="django_admin",
                event_type="agent.token.admin_revoked",
                reason="admin_selected_revoke",
            )
        )
        self.assertTrue(
            AuditOutbox.objects.filter(
                event_type="agent.token.admin_revoked",
                event__target__id=str(token.pk),
            ).exists()
        )
