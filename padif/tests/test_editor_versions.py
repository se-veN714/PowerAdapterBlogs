"""Explicit editor snapshots must agree with source, annotations and commit bases."""
from django.test import TestCase, override_settings
from django.urls import reverse

from agent_mcp.tests import test_mcp
from padif.models import Annotation, Version, DocumentCollaborator
from django.utils import timezone
from padif.services import create_branch, commit_document_version


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False,
    SESSION_ENGINE='django.contrib.sessions.backends.db')
class EditorVersionTests(TestCase):
    def setUp(self):
        test_mcp.OAuthMcpTests.setUp(self)
        self.branch = create_branch(document_id=self.document.pk, user=self.owner, name='writing', fork_from_version_id=self.head)
        self.old = commit_document_version(document_id=self.document.pk, user=self.owner, branch_id=self.branch.pk,
            base_version_id=self.head, content='# Old\n\nEarlier paragraph.', commit_message='Earlier', version_kind='patch').version
        self.latest = commit_document_version(document_id=self.document.pk, user=self.owner, branch_id=self.branch.pk,
            base_version_id=self.old.pk, content='# Latest\n\nLatest paragraph.', commit_message='Latest', version_kind='patch').version
        self.url = reverse('padif:document_detail', args=[self.document.pk])
        self.client.force_login(self.owner)

    def test_current_branch_head_has_explicit_identity_and_editable_form(self):
        response = self.client.get(self.url, {'branch': 'writing'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['current_version'].pk, self.latest.pk)
        self.assertFalse(response.context['is_historical'])
        self.assertTrue(response.context['can_edit_version'])
        self.assertContains(response, f'data-version="{self.latest.pk}"')
        self.assertContains(response, 'data-editor-version')
        self.assertEqual(response.context['commit_form']['base_version_id'].value(), self.latest.pk)

    def test_historical_source_annotations_diff_base_and_graph_are_consistent(self):
        note = Annotation.objects.create(version=self.old, author=self.owner, kind='question', body='Old note', start_line=1, end_line=1)
        response = self.client.get(self.url, {'branch': 'writing', 'version': self.old.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['current_version'].pk, self.old.pk)
        self.assertEqual(response.context['head_version'].pk, self.latest.pk)
        self.assertEqual(response.context['commit_form']['content'].value(), self.old.content)
        self.assertEqual(list(response.context['annotations']), [note])
        self.assertFalse(response.context['can_edit_version'])
        self.assertEqual(response.context['diff_form']['to_version'].value(), self.old.pk)
        self.assertContains(response, '历史正文 · 只读')
        self.assertNotContains(response, '>保存新版本</button>')
        self.assertContains(response, f'version={self.old.pk}')

    def test_old_node_outside_recent_three_remains_in_diagram(self):
        for index in range(4):
            self.latest = commit_document_version(document_id=self.document.pk, user=self.owner, branch_id=self.branch.pk,
                base_version_id=self.latest.pk, content=f'# New {index}', commit_message='New', version_kind='patch').version
        response = self.client.get(self.url, {'branch': 'writing', 'version': self.old.pk})
        self.assertIn(self.old.pk, [item['version'].pk for item in response.context['worldlines']['nodes']])

    def test_source_version_can_be_viewed_in_empty_fork_context(self):
        empty = create_branch(document_id=self.document.pk, user=self.owner, name='empty', fork_from_version_id=self.old.pk)
        response = self.client.get(self.url, {'branch': empty.name, 'version': self.old.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_branch'].pk, empty.pk)
        self.assertFalse(response.context['is_historical'])

    def test_unknown_cross_branch_or_malformed_version_is_not_silently_replaced(self):
        for query in [dict(version='bad'), dict(version='9'*100), dict(version='²'), dict(version='-1'), dict(version='999999'),
                dict(branch='main', version=self.old.pk)]:
            self.assertEqual(self.client.get(self.url, query).status_code, 404, query)
        other_document = type(self.document).objects.create(title='Private', created_by=self.owner)
        self.assertEqual(self.client.get(reverse('padif:document_detail', args=[other_document.pk]), {'version': self.old.pk}).status_code, 404)

    def test_version_only_resolves_its_actual_branch(self):
        response = self.client.get(self.url, {'version': self.old.pk})
        self.assertEqual(response.context['selected_branch'].pk, self.branch.pk)
        self.assertEqual(response.context['current_version'].pk, self.old.pk)

    def test_stale_save_retains_input_and_old_identity_without_resetting_head(self):
        before = Version.objects.count()
        response = self.client.post(reverse('padif:commit_version', args=[self.document.pk]), {
            'branch_id': self.branch.pk, 'base_version_id': self.old.pk, 'content': '# My unsaved draft',
            'commit_message': 'Draft message', 'version_kind': 'patch'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.context['current_version'].pk, self.old.pk)
        self.assertTrue(response.context['editor_conflicted'])
        self.assertEqual(response.context['commit_form']['content'].value(), '# My unsaved draft')
        self.assertEqual(int(response.context['commit_form']['base_version_id'].value()), self.old.pk)
        self.assertEqual(Version.objects.count(), before)
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version_id, self.head)

    def test_archived_and_viewer_pages_have_no_edit_submission(self):
        self.branch.archived_at = timezone.now()
        self.branch.save()
        response = self.client.get(self.url, {'branch': 'writing'})
        self.assertFalse(response.context['can_edit_version'])
        self.assertNotContains(response, '>保存新版本</button>')
        viewer = type(self.owner).objects.create_user(username='editor-viewer', email='viewer@example.test', password='local', is_active=True)
        viewer.user_permissions.set(self.owner.user_permissions.all())
        DocumentCollaborator.objects.create(document=self.document, user=viewer, granted_by=self.owner, role='viewer')
        self.client.force_login(viewer)
        response = self.client.get(self.url, {'version': self.old.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['can_edit_version'])
        self.assertNotContains(response, '>保存新版本</button>')
