import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from oauth2_provider.models import Application

from accounts.agent_auth import create_device_authorization, approve_device_authorization, issue_access_token
from agent_mcp.access import revoke_agent_qualification
from agent_mcp.models import AgentQualification, Connection, WriteReceipt
from agent_mcp.tools import call_tool
from padif.collaboration import set_collaboration
from padif.models import Annotation, DocumentAgentGrant, DocumentCollaborator
from padif.permissions import visible_documents
from padif.services import create_document_from_upload, create_branch, commit_document_version, publish_branch


@override_settings(MFA_ENFORCEMENT_ENABLED=False, PUBLIC_SITE_URL='https://testserver')
class DocumentCollaborationTests(TestCase):
    def setUp(self):
        self.owner = self.user('owner')
        self.viewer = self.user('viewer')
        self.writer = self.user('writer')
        self.stranger = self.user('stranger')
        self.admin = self.user('admin', is_superuser=True, is_staff=True)
        self.document = self.make_document(self.owner, 'Private draft')
        self.other = self.make_document(self.stranger, 'Unrelated private draft')
        self.head = self.document.current_version
        self.annotation = Annotation.objects.create(version=self.head, author=self.owner,
            kind='question', body='Private question', start_line=1, end_line=1)
        self.change(self.viewer, 'role', role='viewer')
        self.change(self.writer, 'role', role='collaborator')
        self.app = Application.objects.create(name='ACL Agent', client_type='public',
            authorization_grant_type='authorization-code', redirect_uris='http://127.0.0.1:9919/callback')

    def user(self, name, **extra):
        user = get_user_model().objects.create_user(username=name, email=name+'@example.test', password='local-test', is_active=True, **extra)
        user.user_permissions.add(Permission.objects.get(content_type__app_label='padif', codename='use_padif'))
        AgentQualification.objects.create(user=user, is_active=True)
        return user

    def make_document(self, owner, title):
        return create_document_from_upload(user=owner, upload=SimpleUploadedFile('draft.md', b'# Title\n\nPrivate manuscript.'),
            title=title, commit_message='Initial').document

    def change(self, user, action, **kwargs):
        return set_collaboration(document_id=self.document.pk, actor=self.owner,
            username=user.username, action=action, note='Local ACL decision', **kwargs)

    def connection(self, user):
        return Connection.objects.create(user=user, application=self.app, family=uuid.uuid4(),
            scopes=['padif:read', 'padif:annotate', 'padif:version'], expires_at=timezone.now()+timedelta(days=1))

    def token(self, user):
        device = create_device_authorization(client_name='ACL', scopes=['padif:read', 'padif:annotate', 'padif:version'])
        approve_device_authorization(user=user, user_code=device['user_code'], approve=True)
        issued = issue_access_token(authorization=device['authorization'], device_code=device['device_code'])
        return {'HTTP_AUTHORIZATION': 'Bearer '+issued['access_token']}

    def test_unshared_accounts_including_admin_cannot_discover_or_read(self):
        for user in (self.stranger, self.admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertNotContains(self.client.get('/padif/'), self.document.title)
                self.assertEqual(self.client.get(reverse('padif:document_detail', args=[self.document.pk])).status_code, 404)
                self.assertEqual(self.client.get(reverse('padif:diff_fragment', args=[self.document.pk])).status_code, 404)
                self.assertEqual(self.client.get(reverse('padif:collaboration', args=[self.document.pk])).status_code, 404)
                self.assertEqual(call_tool(self.connection(user), 'get_version', {'version_id': self.head.pk})['error'], 'NOT_FOUND')
        self.client.logout()
        self.assertEqual(self.client.get(reverse('padif:document_detail', args=[self.document.pk])).status_code, 302)

    def test_viewer_reads_threads_but_cannot_write_or_manage(self):
        self.client.force_login(self.viewer)
        detail = self.client.get(reverse('padif:document_detail', args=[self.document.pk]))
        self.assertContains(detail, 'Private manuscript.')
        self.assertContains(detail, 'Private question')
        self.assertNotContains(detail, 'data-padif-annotation-form method=')
        self.assertNotContains(detail, 'class="main-add-version"')
        for name, args in [('commit_version', [self.document.pk]), ('upload_version', [self.document.pk]),
            ('create_branch', [self.document.pk]), ('create_annotation', [self.document.pk, self.head.pk]),
            ('update_annotation', [self.document.pk, self.annotation.pk]),
            ('create_annotation_reply', [self.document.pk, self.annotation.pk]), ('collaboration', [self.document.pk])]:
            self.assertEqual(self.client.post(reverse('padif:'+name, args=args), {}).status_code, 403, name)

    def test_collaborator_writes_branch_but_only_owner_publishes(self):
        branch = create_branch(document_id=self.document.pk, user=self.writer, name='rewrite', fork_from_version_id=self.head.pk)
        version = commit_document_version(document_id=self.document.pk, user=self.writer, branch_id=branch.pk,
            base_version_id=self.head.pk, content='Revised', commit_message='Rewrite', version_kind='patch').version
        with self.assertRaises(PermissionDenied):
            commit_document_version(document_id=self.document.pk, user=self.writer,
                content='Direct main', commit_message='No', version_kind='patch')
        with self.assertRaises(PermissionDenied):
            publish_branch(document_id=self.document.pk, branch_id=branch.pk, user=self.writer,
                base_version_id=self.head.pk, source_version_id=version.pk, commit_message='No', version_kind='patch', confirm_replace=True)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(reverse('padif:collaboration', args=[self.document.pk])).status_code, 403)
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version_id, self.head.pk)

    def test_ai_opt_in_is_required_even_for_owner(self):
        self.assertFalse(DocumentAgentGrant.objects.exists())
        self.assertFalse(visible_documents(self.owner, agent=True).exists())
        connection = self.connection(self.owner)
        self.assertEqual(call_tool(connection, 'get_workspace', {'document_id': self.document.pk})['error'], 'DOCUMENT_PERMISSION_DENIED')
        self.change(self.owner, 'ai', enabled=True)
        self.assertEqual(list(visible_documents(self.owner, agent=True)), [self.document])
        self.assertNotIn('error', call_tool(connection, 'get_workspace', {'document_id': self.document.pk}))

    def test_viewer_ai_is_read_only_even_with_all_token_scopes(self):
        self.change(self.viewer, 'ai', enabled=True)
        connection = self.connection(self.viewer)
        self.assertNotIn('error', call_tool(connection, 'get_version', {'version_id': self.head.pk}))
        self.assertEqual(call_tool(connection, 'reply_annotation', {'annotation_id': self.annotation.pk,
            'body': 'Unauthorized', 'request_id': 'viewer-reply'})['error'], 'DOCUMENT_PERMISSION_DENIED')
        headers = self.token(self.viewer)
        self.assertEqual(self.client.post(reverse('padif:agent-create-reply', args=[self.annotation.pk]),
            json.dumps({'body': 'No'}), content_type='application/json', **headers).status_code, 403)

    def test_legacy_api_uses_identical_document_and_ai_gates(self):
        headers = self.token(self.owner)
        url = reverse('padif:agent-workspace', args=[self.document.pk])
        self.assertEqual(self.client.get(url, **headers).status_code, 403)
        self.change(self.owner, 'ai', enabled=True)
        self.assertEqual(self.client.get(url, **headers).status_code, 200)
        self.assertEqual(self.client.post(reverse('padif:agent-commit-version', args=[self.document.pk]),
            json.dumps({'content': 'No', 'commit_message': 'No', 'version_kind': 'patch'}), content_type='application/json', **headers).status_code, 403)
        self.assertEqual(self.client.get(reverse('padif:agent-workspace', args=[self.other.pk]), **headers).status_code, 404)
        other_annotation = Annotation.objects.create(version=self.other.current_version, author=self.stranger,
            kind='question', body='Secret', start_line=1, end_line=1)
        self.assertEqual(self.client.post(reverse('padif:agent-create-reply', args=[other_annotation.pk]),
            json.dumps({'body':'No'}), content_type='application/json', **headers).status_code, 404)

    def test_role_changes_removal_and_qualification_revocation_disable_ai(self):
        self.change(self.writer, 'ai', enabled=True)
        self.change(self.writer, 'role', role='viewer')
        self.assertFalse(DocumentAgentGrant.objects.get(user=self.writer, document=self.document).is_enabled)
        self.change(self.writer, 'ai', enabled=True)
        self.change(self.writer, 'remove')
        self.assertFalse(visible_documents(self.writer).exists())
        self.change(self.writer, 'role', role='collaborator')
        self.assertFalse(DocumentAgentGrant.objects.get(user=self.writer, document=self.document).is_enabled)
        self.change(self.writer, 'ai', enabled=True)
        revoke_agent_qualification(self.writer.pk, self.admin, 'Local policy test')
        self.assertFalse(DocumentAgentGrant.objects.get(user=self.writer, document=self.document).is_enabled)
        with self.assertRaises(ValidationError):
            self.change(self.writer, 'ai', enabled=True)
        AgentQualification.objects.filter(user=self.writer).update(is_active=True)
        self.assertFalse(visible_documents(self.writer, agent=True).exists())

    def test_ai_revocation_precedes_idempotency_receipt_lookup(self):
        self.change(self.writer, 'ai', enabled=True)
        connection = self.connection(self.writer)
        values = {'document_id': self.document.pk, 'name': 'retry-test', 'fork_from_version_id': self.head.pk, 'request_id': 'retry'}
        first = call_tool(connection, 'create_branch', values)
        self.assertNotIn('error', first)
        self.assertTrue(WriteReceipt.objects.filter(connection=connection).exists())
        self.change(self.writer, 'ai', enabled=False)
        self.assertEqual(call_tool(connection, 'create_branch', values)['error'], 'DOCUMENT_PERMISSION_DENIED')
        self.assertEqual(self.document.branches.filter(name='retry-test').count(), 1)

    def test_owner_can_remove_or_disable_ai_for_an_inactive_member(self):
        self.change(self.writer, 'ai', enabled=True)
        self.writer.is_active = False
        self.writer.save(update_fields=['is_active'])
        self.change(self.writer, 'ai', enabled=False)
        self.change(self.writer, 'remove')
        membership = DocumentCollaborator.objects.get(user=self.writer, document=self.document)
        self.assertFalse(membership.is_active)
        self.assertFalse(DocumentAgentGrant.objects.get(user=self.writer, document=self.document).is_enabled)

    def test_only_owner_can_grant_and_no_role_backfill(self):
        with self.assertRaises(PermissionDenied):
            set_collaboration(document_id=self.document.pk, actor=self.writer,
                username=self.stranger.username, action='role', role='viewer')
        self.assertEqual(DocumentCollaborator.objects.filter(document=self.other).count(), 0)
        with self.assertRaises(Http404):
            set_collaboration(document_id=self.document.pk, actor=self.admin,
                username=self.admin.username, action='ai', enabled=True)

    def test_collaborator_mcp_writes_and_owner_web_publication(self):
        self.change(self.writer, 'ai', enabled=True)
        connection = self.connection(self.writer)
        result = call_tool(connection, 'create_branch', {'document_id': self.document.pk,
            'name': 'agent-edit', 'fork_from_version_id': self.head.pk, 'request_id': 'branch'})
        self.assertNotIn('error', result)
        result = call_tool(connection, 'commit_version', {'document_id': self.document.pk,
            'branch': 'agent-edit', 'base_version_id': self.head.pk, 'content': '# Revision\n\nNew paragraph.',
            'commit_message': 'Collaborator revision', 'version_kind': 'patch', 'request_id': 'version'})
        self.assertNotIn('error', result)
        branch = self.document.branches.get(name='agent-edit')
        version = branch.versions.latest('pk')
        result = call_tool(connection, 'add_annotation', {'version_id': version.pk,
            'kind': 'question', 'body': 'Confirm revision?', 'start_line': 3, 'end_line': 3, 'request_id': 'note'})
        self.assertNotIn('error', result)
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version_id, self.head.pk)
        self.client.force_login(self.owner)
        response = self.client.post(reverse('padif:publish_branch', args=[self.document.pk, branch.pk]),
            {'base_version_id': self.head.pk, 'source_version_id': version.pk, 'confirm_replace': 'on',
             'commit_message': 'Reviewed on web', 'version_kind': 'patch'})
        self.assertEqual(response.status_code, 302)
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version.content, version.content)
