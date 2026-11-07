from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, override_settings

from agent_mcp.access import can_use_agent, submit_agent_request, decide_agent_request
from agent_mcp.models import AgentQualification, AgentAccessRequest
from accounts.agent_auth import approve_device_authorization, create_device_authorization, issue_access_token, authenticate_agent_token
from security.models import AuditOutbox
from . import test_mcp


@override_settings(PUBLIC_SITE_URL='https://testserver', SESSION_ENGINE='django.contrib.sessions.backends.db', MFA_ENFORCEMENT_ENABLED=False,
                   CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class AgentAccessReviewTests(TestCase):
    authorize = test_mcp.OAuthMcpTests.authorize
    issue = test_mcp.OAuthMcpTests.issue
    rpc = test_mcp.OAuthMcpTests.rpc
    refresh = test_mcp.OAuthMcpTests.refresh

    def setUp(self):
        test_mcp.OAuthMcpTests.setUp(self)
        AgentQualification.objects.filter(user=self.owner).delete()
        self.reviewer = get_user_model().objects.create_superuser(username='agent-reviewer', email='reviewer@example.test', password='test-password')

    def apply_and_approve(self):
        item = submit_agent_request(self.owner, 'Writing and annotation assistance')
        return decide_agent_request(item.pk, self.reviewer, True, 'Approved for writing assistance')

    def test_unapproved_user_cannot_authorize_or_self_grant(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get('/accounts/security/agents/', secure=True), '申请开通 PAdif Agent')
        response = self.client.get('/accounts/agent/oauth/authorize/', self.params, secure=True)
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, '先开通 Agent 使用资格', status_code=403)
        device = create_device_authorization(client_name='Blocked')
        with self.assertRaises(PermissionError):
            approve_device_authorization(user=self.owner, user_code=device['user_code'], approve=True)
        item = submit_agent_request(self.owner, 'Writing')
        with self.assertRaises(PermissionDenied):
            decide_agent_request(item.pk, self.owner, True, 'Self approval')
        self.assertFalse(can_use_agent(self.owner))

    def test_dashboard_entry_approval_and_pending_duplicate(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post('/accounts/agent/oauth/apply/', {'module_key': 'padif'}, secure=True).status_code, 302)
        self.client.post('/accounts/agent/oauth/apply/', {'module_key': 'padif'}, secure=True)
        self.assertEqual(AgentAccessRequest.objects.count(), 1)
        self.assertEqual(self.client.get('/dashboard/agents/', secure=True).status_code, 403)
        self.client.force_login(self.reviewer)
        page = self.client.get('/dashboard/agents/', secure=True)
        self.assertContains(page, 'Agent 审核')
        item = AgentAccessRequest.objects.get()
        self.client.post('/dashboard/agents/', {'request_id': item.pk, 'action': 'approve', 'note': ' '}, secure=True)
        self.assertFalse(can_use_agent(self.owner))
        self.client.post('/dashboard/agents/', {'request_id': item.pk, 'action': 'approve', 'note': 'Approved'}, secure=True)
        self.assertTrue(can_use_agent(self.owner))
        with self.assertRaises(ValidationError):
            decide_agent_request(item.pk, self.reviewer, True, 'Duplicate decision')
        issued = self.issue(['padif:read'])
        self.assertEqual(len(self.rpc(issued['access_token'], 'tools/list').json()['result']['tools']), 5)

    def test_revocation_blocks_oauth_refresh_and_legacy_tokens_and_retains_history(self):
        item = self.apply_and_approve()
        issued = self.issue()
        device = create_device_authorization(client_name='Legacy approved')
        approved = approve_device_authorization(user=self.owner, user_code=device['user_code'], approve=True)
        legacy = issue_access_token(authorization=approved, device_code=device['device_code'])['access_token']
        self.client.force_login(self.reviewer)
        self.client.post('/dashboard/agents/', {'request_id': item.pk, 'action': 'revoke', 'note': 'Access no longer needed'}, secure=True)
        self.assertFalse(can_use_agent(self.owner))
        self.assertEqual(self.rpc(issued['access_token'], 'tools/list').status_code, 401)
        self.assertEqual(self.refresh(issued['refresh_token']).status_code, 400)
        self.assertIsNone(authenticate_agent_token(legacy)[0])
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')
        self.assertEqual(item.decision_note, 'Approved for writing assistance')
        self.assertTrue(AuditOutbox.objects.filter(event_type='agent.access.revoked').exists())

    def test_rejection_allows_reapply_without_granting_padif_or_agent(self):
        item = submit_agent_request(self.owner, 'Writing')
        decide_agent_request(item.pk, self.reviewer, False, 'Please clarify purpose')
        self.assertFalse(can_use_agent(self.owner))
        self.assertEqual(submit_agent_request(self.owner, 'More detailed writing purpose').status, 'pending')
        self.owner.user_permissions.clear()
        with self.assertRaises(PermissionDenied):
            submit_agent_request(get_user_model().objects.get(pk=self.owner.pk), 'No PAdif permission')
