import json
from uuid import uuid4

from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from agent_mcp.tests import test_mcp
from padif.models import Document, EditorDraft, Version, DocumentCollaborator
from padif.services import create_branch, commit_document_version


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False,
                   SESSION_ENGINE='django.contrib.sessions.backends.db')
class CloudDraftTests(TestCase):
    def setUp(self):
        test_mcp.OAuthMcpTests.setUp(self)
        self.other = get_user_model().objects.create_user(username='other-draft-writer', email='other-draft@example.test', password='local-test-password', is_active=True)
        self.other.user_permissions.add(Permission.objects.get(content_type__app_label='padif', codename='use_padif'))
        self.branch = create_branch(document_id=self.document.pk, user=self.owner, name='writing', fork_from_version_id=self.head)
        self.url = reverse('padif:editor-draft', args=[self.document.pk, self.branch.pk, self.head])
        self.client.force_login(self.owner)

    def save(self, **changes):
        values = {'action': 'save', 'revision': '', 'content': '# Private work in progress',
                  'commit_message': '', 'version_kind': 'patch', **changes}
        return self.client.post(self.url, json.dumps(values), content_type='application/json')

    def test_save_relogin_restore_without_any_version_or_head_change(self):
        before = list(Version.objects.values())
        heads = list(Document.objects.values('pk', 'current_version_id'))
        response = self.save()
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.client.logout()
        self.client.force_login(self.owner)
        restored = self.client.get(self.url).json()['draft']
        self.assertEqual(restored['content'], '# Private work in progress')
        self.assertEqual(restored['commit_message'], '')
        self.assertEqual(restored['base_version_id'], self.head)
        self.assertEqual(list(Version.objects.values()), before)
        self.assertEqual(list(Document.objects.values('pk', 'current_version_id')), heads)

    def test_optimistic_save_and_delete_reject_other_tabs_and_recreated_draft(self):
        first = self.save().json()['draft']['revision']
        self.assertEqual(self.save().status_code, 409)
        second = self.save(revision=first, content='Newer work').json()['draft']['revision']
        self.assertNotEqual(second, first)
        self.assertEqual(self.save(revision=first).status_code, 409)
        self.assertEqual(self.save(action='delete', revision=first).status_code, 409)
        self.assertEqual(self.save(action='delete', revision=second).status_code, 200)
        recreated = self.save().json()['draft']['revision']
        self.assertNotEqual(recreated, first)
        self.assertEqual(self.save(revision=second).status_code, 409)

    def test_private_even_for_another_authorized_collaborator(self):
        self.save()
        DocumentCollaborator.objects.update_or_create(document=self.document, user=self.other,
            defaults={'role': 'collaborator', 'is_active': True, 'granted_by': self.owner})
        self.client.force_login(self.other)
        self.assertIsNone(self.client.get(self.url).json()['draft'])
        self.assertEqual(self.save(content='Other personal draft').status_code, 200)
        self.assertEqual(EditorDraft.objects.count(), 2)

    def test_viewer_anonymous_and_revoked_members_cannot_write(self):
        self.save()
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.other)
        DocumentCollaborator.objects.update_or_create(document=self.document, user=self.other,
            defaults={'role': 'viewer', 'is_active': True, 'granted_by': self.owner})
        self.assertEqual(self.save().status_code, 403)
        DocumentCollaborator.objects.filter(document=self.document, user=self.other).update(is_active=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_collaborator_cannot_save_main_and_archived_branch_cannot_save(self):
        DocumentCollaborator.objects.update_or_create(document=self.document, user=self.other,
            defaults={'role': 'collaborator', 'is_active': True, 'granted_by': self.owner})
        self.client.force_login(self.other)
        main = self.document.branches.get(is_default=True)
        self.url = reverse('padif:editor-draft', args=[self.document.pk, main.pk, self.head])
        self.assertEqual(self.save().status_code, 403)
        from django.utils import timezone
        self.branch.archived_at = timezone.now()
        self.branch.save()
        self.url = reverse('padif:editor-draft', args=[self.document.pk, self.branch.pk, self.head])
        self.assertEqual(self.save().status_code, 403)

    def test_stale_base_draft_kept_separately_and_discoverable(self):
        self.save()
        new = commit_document_version(document_id=self.document.pk, user=self.owner, branch_id=self.branch.pk,
            base_version_id=self.head, content='# Committed', commit_message='New', version_kind='patch').version
        newer_url = reverse('padif:editor-draft', args=[self.document.pk, self.branch.pk, new.pk])
        response = self.client.get(newer_url).json()
        self.assertIsNone(response['draft'])
        self.assertEqual(response['other_drafts'][0]['base_version_id'], self.head)
        original = self.client.get(self.url).json()['draft']
        self.assertEqual(self.save(revision=original['revision'], content='Still private').status_code, 200)
        self.assertEqual(Version.objects.get(pk=new.pk).content, '# Committed')

    def test_invalid_json_size_and_cross_document_bases_rejected(self):
        for content in ('[]', '{bad', json.dumps({'revision': 1}), json.dumps({'revision': str(uuid4()), 'content': 1})):
            self.assertEqual(self.client.post(self.url, content, content_type='application/json').status_code, 400)
        self.assertEqual(self.save(content='x' * (2 * 1024 * 1024)).status_code, 413)
        self.assertEqual(self.client.post(self.url, {}).status_code, 415)
        self.assertEqual(self.save(content='bad\x00text').status_code, 400)
        self.assertEqual(self.save(content='bad\ud800text').status_code, 400)
        foreign = Document.objects.create(title='Different', created_by=self.owner)
        self.url = reverse('padif:editor-draft', args=[foreign.pk, self.branch.pk, self.head])
        self.assertEqual(self.save().status_code, 404)

    def test_successful_commit_removes_only_exact_saved_draft(self):
        revision = self.save().json()['draft']['revision']
        response = self.client.post(reverse('padif:commit_version', args=[self.document.pk]), {
            'branch_id': self.branch.pk, 'base_version_id': self.head, 'branch_context': 'writing',
            'content': '# Private work in progress', 'commit_message': 'Complete article',
            'version_kind': 'patch', 'draft_revision': revision})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(EditorDraft.objects.count(), 0)

    def test_newer_other_tab_draft_survives_commit_of_older_draft(self):
        revision = self.save().json()['draft']['revision']
        self.save(revision=revision, content='Newer unsent work')
        response = self.client.post(reverse('padif:commit_version', args=[self.document.pk]), {
            'branch_id': self.branch.pk, 'base_version_id': self.head, 'branch_context': 'writing',
            'content': '# Private work in progress', 'commit_message': 'Complete article',
            'version_kind': 'patch', 'draft_revision': revision})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(EditorDraft.objects.get().content, 'Newer unsent work')

    def test_stale_commit_keeps_cloud_draft_and_does_not_add_version(self):
        revision = self.save().json()['draft']['revision']
        commit_document_version(document_id=self.document.pk, user=self.owner, branch_id=self.branch.pk,
            base_version_id=self.head, content='New branch head', commit_message='Other work', version_kind='patch')
        count = Version.objects.count()
        response = self.client.post(reverse('padif:commit_version', args=[self.document.pk]), {
            'branch_id': self.branch.pk, 'base_version_id': self.head, 'branch_context': 'writing',
            'content': '# Private work in progress', 'commit_message': 'Complete article',
            'version_kind': 'patch', 'draft_revision': revision})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(EditorDraft.objects.get().content, '# Private work in progress')
        self.assertEqual(Version.objects.count(), count)

    def test_session_write_requires_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(self.url, '{}', content_type='application/json').status_code, 403)
        self.assertFalse(EditorDraft.objects.exists())
