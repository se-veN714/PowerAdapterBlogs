from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from padif.tests import test_collaboration
from padif.agent_requests import submit_document_requests, decide_document_request


@override_settings(MFA_ENFORCEMENT_ENABLED=False, PUBLIC_SITE_URL='https://testserver')
class CollaborationPresentationTests(TestCase):
    setUp = test_collaboration.DocumentCollaborationTests.setUp
    user = test_collaboration.DocumentCollaborationTests.user
    make_document = test_collaboration.DocumentCollaborationTests.make_document
    change = test_collaboration.DocumentCollaborationTests.change

    def test_account_picker_searches_name_and_id_without_exposing_email(self):
        self.client.force_login(self.owner)
        url = reverse('padif:collaboration', args=[self.document.pk])
        for query in [self.viewer.username, str(self.viewer.pk)]:
            response = self.client.get(url, {'accounts': '1', 'q': query})
            self.assertEqual(response.status_code, 200)
            rows = response.json()['accounts']
            self.assertTrue(any(row['id'] == self.viewer.pk for row in rows))
            self.assertTrue(all(set(row) == {'id', 'username'} for row in rows))
        inactive = self.user('inactive-picker')
        get_user_model().objects.filter(pk=inactive.pk).update(is_active=False)
        response = self.client.get(url, {'accounts': '1', 'q': 'inactive-picker'})
        self.assertEqual(response.json()['accounts'], [])
        no_capability = self.user('no-capability-picker')
        no_capability.user_permissions.clear()
        response = self.client.get(url, {'accounts': '1', 'q': no_capability.username})
        self.assertEqual(response.json()['accounts'], [])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.client.get(url, {'accounts': '1', 'q': self.owner.username}).json()['accounts'], [])
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url, {'accounts': '1'}).status_code, 403)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(url, {'accounts': '1'}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url, {'accounts': '1'}).status_code, 302)

    def test_document_and_collaboration_distinguish_module_pending_and_effective(self):
        self.client.force_login(self.owner)
        detail = reverse('padif:document_detail', args=[self.document.pk])
        manage = reverse('padif:collaboration', args=[self.document.pk])
        self.assertContains(self.client.get(detail), 'PAdif Agent 已开通')
        self.assertContains(self.client.get(detail), '本文 AI+ 未授权')
        item = submit_document_requests(self.owner, [self.document.pk], 'Read and annotate')[0]
        for url in [detail, manage]:
            self.assertContains(self.client.get(url), '本文 AI+ 待审核')
        self.assertContains(self.client.get(detail), 'document-manage-collaboration')
        decide_document_request(item.pk, self.owner, True, 'Owner approved')
        for url in [detail, manage]:
            self.assertContains(self.client.get(url), '本文 AI+ 已生效')

    def test_page_preserves_owner_controls_and_no_implicit_article_access(self):
        self.client.force_login(self.owner)
        url = reverse('padif:collaboration', args=[self.document.pk])
        page = self.client.get(url)
        self.assertContains(page, 'data-account-picker')
        self.assertContains(page, '主线发布仍由创建者在网页确认')
        self.client.post(url, {'action': 'role', 'username': self.stranger.username, 'role': 'collaborator'})
        self.assertFalse(self.document.agent_grants.filter(user=self.stranger, is_enabled=True).exists())

    def test_personal_agent_page_owner_can_approve_self_without_dashboard_access(self):
        self.client.force_login(self.owner)
        item = submit_document_requests(self.owner, [self.document.pk], 'Own manuscript')[0]
        page = self.client.get('/accounts/security/agents/', secure=True)
        self.assertContains(page, '我创建文章的 AI+ 审批')
        self.assertContains(page, f'data-owned-ai-request="{item.pk}"')
        self.assertContains(page, '管理本文授权')
        url = reverse('agent_mcp:review-article', args=[item.pk])
        self.client.post(url, {'decision': 'approve', 'note': ''}, secure=True)
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')
        self.client.post(url, {'decision': 'approve', 'note': 'Owner confirms access'}, secure=True)
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')
        self.assertTrue(self.document.agent_grants.get(user=self.owner).is_enabled)
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version_id, self.head.pk)

    def test_owner_inbox_does_not_leak_or_delegate_article_authority(self):
        from django.test import Client
        item = submit_document_requests(self.owner, [self.document.pk], 'Own manuscript')[0]
        url = reverse('agent_mcp:review-article', args=[item.pk])
        for user in [self.viewer, self.stranger, self.admin]:
            self.client.force_login(user)
            page = self.client.get('/accounts/security/agents/', secure=True)
            self.assertNotContains(page, f'data-owned-ai-request="{item.pk}"')
            self.assertIn(self.client.post(url, {'decision': 'approve', 'note': 'Forged approval'}, secure=True).status_code, [403, 404])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url, secure=True).status_code, 405)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        self.assertEqual(guarded.post(url, {'decision': 'approve', 'note': 'No CSRF'}, secure=True).status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')

    def test_owner_inbox_rejects_invalid_decision_and_terminal_reapproval(self):
        self.client.force_login(self.owner)
        item = submit_document_requests(self.owner, [self.document.pk], 'Own manuscript')[0]
        url = reverse('agent_mcp:review-article', args=[item.pk])
        self.client.post(url, {'decision': 'anything', 'note': 'Invalid'}, secure=True)
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')
        self.client.post(url, {'decision': 'reject', 'note': 'Do not share this draft'}, secure=True)
        self.client.post(url, {'decision': 'approve', 'note': 'Stale form'}, secure=True)
        item.refresh_from_db()
        self.assertEqual(item.status, 'rejected')
        self.assertEqual(item.decision_note, 'Do not share this draft')
        self.assertFalse(self.document.agent_grants.filter(is_enabled=True).exists())
