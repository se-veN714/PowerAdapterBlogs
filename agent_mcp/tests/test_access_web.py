from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model

from padif.tests import test_agent_requests
from padif.models import DocumentAgentRequest, DocumentAgentGrant
from padif.collaboration import set_collaboration
from agent_mcp.access import revoke_agent_qualification


@override_settings(MFA_ENFORCEMENT_ENABLED=False, PUBLIC_SITE_URL='https://testserver', SESSION_ENGINE='django.contrib.sessions.backends.db')
class TwoLevelAccessWebTests(TestCase):
    setUp = test_agent_requests.ArticleAgentRequestTests.setUp

    def test_module_selection_is_fixed_and_application_needs_no_free_text(self):
        revoke_agent_qualification(self.user.pk, self.owner, 'Reset for module application')
        self.client.force_login(self.user)
        page = self.client.get('/accounts/security/agents/', secure=True)
        self.assertContains(page, 'id="agent-module"')
        self.assertNotContains(page, 'id="agent-access-reason"')
        self.assertEqual(self.client.post(reverse('agent_mcp:apply'), {'module_key': 'padif'}, secure=True).status_code, 302)
        from agent_mcp.models import AgentAccessRequest
        item = AgentAccessRequest.objects.get(applicant=self.user, status='pending')
        self.assertEqual(item.reason, '')
        self.assertEqual(item.module_key, 'padif')
        item.full_clean()

    def test_web_application_rejects_missing_or_unsupported_module(self):
        from agent_mcp.models import AgentAccessRequest
        revoke_agent_qualification(self.user.pk, self.owner, 'Reset module')
        self.client.force_login(self.user)
        for payload in [{}, {'module_key': 'other'}, {'module_key': '1'}]:
            self.client.post(reverse('agent_mcp:apply'), payload, secure=True)
            self.assertFalse(AgentAccessRequest.objects.filter(applicant=self.user, status='pending').exists())

    def test_owner_portal_links_to_article_management_without_embedding_human_controls(self):
        self.client.force_login(self.owner)
        management_url = reverse('padif:collaboration', args=[self.document.pk])
        portal = self.client.get('/accounts/security/agents/', secure=True)
        self.assertContains(portal, management_url)
        self.assertNotContains(portal, 'id="collaboration-account"')
        self.assertNotContains(portal, '创建者直接授权 / 审核本文申请')
        self.assertContains(portal, reverse('padif:document_detail', args=[self.document.pk]))
        detail = self.client.get(reverse('padif:document_detail', args=[self.document.pk]), secure=True)
        self.assertContains(detail, management_url)
        management = self.client.get(management_url, secure=True)
        self.assertContains(management, '协作成员')
        self.assertContains(management, '待审核申请')

    def test_article_application_owner_approval_and_self_relinquish(self):
        self.client.force_login(self.user)
        page = self.client.get('/accounts/security/agents/', secure=True)
        self.assertContains(page, '尚无可访问文章')
        self.assertContains(page, self.document.title)
        self.assertEqual(self.client.post(reverse('agent_mcp:apply-articles'), {'document_ids': [self.document.pk], 'reason': 'Read'}, secure=True).status_code, 302)
        item = DocumentAgentRequest.objects.get()
        self.assertFalse(DocumentAgentGrant.objects.filter(user=self.user, is_enabled=True).exists())
        self.client.force_login(self.owner)
        url = reverse('padif:collaboration', args=[self.document.pk])
        self.assertContains(self.client.get(url, secure=True), '待审核申请')
        self.assertEqual(self.client.post(url, {'action': 'approve-ai', 'request_id': item.pk, 'note': 'Approved'}, secure=True).status_code, 302)
        self.client.force_login(self.user)
        self.assertContains(self.client.get('/accounts/security/agents/', secure=True), '已授权 <strong data-granted-count>1</strong> 篇')
        self.client.post(reverse('agent_mcp:relinquish-article', args=[self.document.pk]), {'note': 'Finished'}, secure=True)
        self.assertFalse(DocumentAgentGrant.objects.get(user=self.user, document=self.document).is_enabled)
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')

    def test_current_module_status_is_independent_of_old_approved_history(self):
        revoke_agent_qualification(self.user.pk, self.owner, 'Finished')
        self.client.force_login(self.user)
        page = self.client.get('/accounts/security/agents/', secure=True)
        self.assertEqual(page.context['module_status'], '已撤销')
        self.assertContains(page, '已批准')
        self.assertContains(page, '申请开通 PAdif Agent')

    def test_member_cannot_approve_and_history_does_not_reveal_lost_articles(self):
        self.client.force_login(self.user)
        self.client.post(reverse('agent_mcp:apply-articles'), {'document_ids': [self.document.pk], 'reason': 'Read'}, secure=True)
        item = DocumentAgentRequest.objects.get()
        self.assertEqual(self.client.post(reverse('padif:collaboration', args=[self.document.pk]),
            {'action': 'approve-ai', 'request_id': item.pk, 'note': 'Self grant'}, secure=True).status_code, 403)
        set_collaboration(document_id=self.document.pk, actor=self.owner, username=self.user.username, action='remove')
        page = self.client.get('/accounts/security/agents/', secure=True)
        self.assertNotContains(page, self.document.title)
        self.assertContains(page, '文章已不可见')
        stranger = get_user_model().objects.create_superuser(username='web-stranger', email='web-stranger@example.test', password='local')
        self.client.force_login(stranger)
        self.assertEqual(self.client.post(reverse('agent_mcp:withdraw-article', args=[item.pk]), secure=True).status_code, 404)

    def test_application_actions_require_post_and_csrf(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('agent_mcp:apply-articles'), secure=True).status_code, 405)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(reverse('agent_mcp:apply-articles'), {'document_ids': [self.document.pk], 'reason': 'Read'}, secure=True).status_code, 403)

    def test_existing_token_sees_new_article_grant_and_immediate_revocation(self):
        from accounts.agent_auth import create_device_authorization, approve_device_authorization, issue_access_token
        from padif.agent_requests import submit_document_requests, decide_document_request, relinquish_document_ai
        device = create_device_authorization(client_name='Existing reader', scopes=['padif:read'])
        approve_device_authorization(user=self.user, user_code=device['user_code'], approve=True)
        token = issue_access_token(authorization=device['authorization'], device_code=device['device_code'])
        headers = {'HTTP_AUTHORIZATION': 'Bearer ' + token['access_token']}
        url = reverse('padif:agent-workspace', args=[self.document.pk])
        self.assertEqual(self.client.get(url, secure=True, **headers).status_code, 403)
        item = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        decide_document_request(item.pk, self.owner, True, 'Approved')
        self.assertEqual(self.client.get(url, secure=True, **headers).status_code, 200)
        relinquish_document_ai(self.document.pk, self.user, 'Finished')
        self.assertEqual(self.client.get(url, secure=True, **headers).status_code, 403)
