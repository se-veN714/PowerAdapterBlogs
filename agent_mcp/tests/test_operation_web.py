from django.test import TestCase, override_settings
from django.urls import reverse
from padif.tests import test_agent_requests
from padif.agent_requests import set_document_ai
from padif.models import DocumentAgentRequest
from padif.collaboration import set_collaboration

@override_settings(MFA_ENFORCEMENT_ENABLED=False, PUBLIC_SITE_URL='https://testserver', SESSION_ENGINE='django.contrib.sessions.backends.db')
class OperationWebTests(TestCase):
    setUp = test_agent_requests.ArticleAgentRequestTests.setUp

    def grant(self):
        set_collaboration(document_id=self.document.pk, actor=self.owner, username=self.user.username, action='role', role='collaborator')
        return set_document_ai(self.document.pk, self.owner, self.user, True, 'Local test')

    def test_drawer_reduces_then_requests_upgrade_and_preserves_invalid_input(self):
        grant = self.grant()
        self.client.force_login(self.user)
        url = reverse('agent_mcp:adjust-article', args=[self.document.pk])
        self.assertContains(self.client.get('/accounts/security/agents/', secure=True), 'id="agent-permission-drawer"')
        response = self.client.post(url, {'operations': ['padif:read'], 'revision': grant.revision, 'note': 'Read only'}, HTTP_ACCEPT='application/json', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('row_html', response.json())
        grant.refresh_from_db()
        bad = self.client.post(url, {'operations': ['padif:read', 'padif:annotate'], 'revision': grant.revision, 'note': ''}, HTTP_ACCEPT='application/json', secure=True)
        self.assertEqual(bad.status_code, 400)
        self.assertIn('error', bad.json())
        self.assertFalse(DocumentAgentRequest.objects.filter(status='pending').exists())
        response = self.client.post(url, {'operations': ['padif:read', 'padif:annotate'], 'revision': grant.revision, 'note': 'Review'}, HTTP_ACCEPT='application/json', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['granted_count'], 1)
        self.assertEqual(response.json()['pending_count'], 1)
        grant.refresh_from_db()
        self.assertEqual(grant.allowed_operations, ['padif:read'])
        self.client.force_login(self.owner)
        page = self.client.get(reverse('padif:collaboration', args=[self.document.pk]), secure=True)
        self.assertContains(page, '阅读 / 批注')
        self.assertContains(page, '提权申请')

    def test_csrf_and_anonymous_gate_remain(self):
        from django.test import Client
        grant = self.grant()
        url = reverse('agent_mcp:adjust-article', args=[self.document.pk])
        self.assertEqual(self.client.post(url, {}, secure=True).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(url, {'operations': [], 'revision': grant.revision, 'note': 'Stop'}, secure=True).status_code, 403)

    def test_removing_own_operations_remains_possible_after_global_capability_loss(self):
        grant = self.grant()
        self.client.force_login(self.user)
        self.user.user_permissions.clear()
        response = self.client.post(reverse('agent_mcp:adjust-article', args=[self.document.pk]),
            {'revision': grant.revision, 'note': 'Remove after capability loss'}, HTTP_ACCEPT='application/json', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['row_html'], '')
        grant.refresh_from_db()
        self.assertFalse(grant.is_enabled)
        self.assertEqual(grant.allowed_operations, [])
