"""Dashboard management of existing users' module eligibility."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from agent_mcp.tests import test_access_states
from agent_mcp.access import grant_agent_qualification, update_agent_qualification, revoke_agent_qualification, can_use_agent
from agent_mcp.models import AgentAccessRequest, AgentQualification
from padif.models import DocumentAgentGrant
from security.models import AuditOutbox

@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False, SESSION_ENGINE='django.contrib.sessions.backends.db')
class DashboardGrantTests(TestCase):
    setUp = test_access_states.ModuleRequestStateTests.setUp

    def test_direct_grant_without_application_and_note_edit_do_not_grant_articles(self):
        grant = grant_agent_qualification(self.user.pk, self.reviewer, 'Invited friend', expected_revision=0)
        self.assertTrue(can_use_agent(self.user))
        self.assertFalse(AgentAccessRequest.objects.exists())
        self.assertFalse(DocumentAgentGrant.objects.exists())
        epoch = grant.revision
        updated = update_agent_qualification(self.user.pk, self.reviewer, 'Revised note', expected_revision=epoch)
        self.assertEqual(updated.revision, epoch)
        self.assertEqual(updated.management_note, 'Revised note')
        self.assertEqual(updated.managed_by_id, self.reviewer.pk)
        self.assertTrue(AuditOutbox.objects.filter(event_type='agent.access.granted').exists())
        self.assertTrue(AuditOutbox.objects.filter(event_type='agent.access.updated').exists())

    def test_search_and_manage_existing_friend_without_an_application(self):
        self.client.force_login(self.reviewer)
        response = self.client.get('/dashboard/agents/', {'q': self.user.username}, secure=True)
        self.assertContains(response, '直接开通 PAdif Agent')
        response = self.client.post('/dashboard/agents/', {'action': 'grant', 'module_key': 'padif', 'user_id': self.user.pk, 'revision': 0, 'note': 'Friend access'}, secure=True)
        self.assertEqual(response.status_code, 302)
        grant = AgentQualification.objects.get(user=self.user)
        self.assertTrue(grant.is_active)
        self.assertFalse(AgentAccessRequest.objects.exists())
        self.client.post('/dashboard/agents/', {'action': 'update', 'module_key': 'padif', 'user_id': self.user.pk, 'revision': grant.revision, 'note': 'Friend writes privately'}, secure=True)
        grant.refresh_from_db()
        self.assertEqual(grant.management_note, 'Friend writes privately')
        self.client.post('/dashboard/agents/', {'action': 'revoke', 'user_id': self.user.pk, 'revision': grant.revision, 'note': 'Paused'}, secure=True)
        grant.refresh_from_db()
        self.assertFalse(grant.is_active)
        page = self.client.get('/dashboard/agents/', {'qualification_status': 'revoked'}, secure=True)
        self.assertContains(page, self.user.username)
        self.assertContains(page, '重新开通')

    def test_pending_application_is_approved_and_restoring_does_not_rewrite_history(self):
        from agent_mcp.access import submit_agent_request
        item = submit_agent_request(self.user, 'Applicant purpose')
        grant = grant_agent_qualification(self.user.pk, self.reviewer, 'Approve existing application', expected_revision=0)
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')
        self.assertEqual(item.decision_note, 'Approve existing application')
        self.assertEqual(AgentAccessRequest.objects.count(), 1)
        revoke_agent_qualification(self.user.pk, self.reviewer, 'Revoke', expected_revision=grant.revision)
        grant.refresh_from_db()
        before = grant.revision
        restored = grant_agent_qualification(self.user.pk, self.reviewer, 'Restore', expected_revision=before)
        self.assertGreater(restored.revision, before)
        self.assertFalse(DocumentAgentGrant.objects.exists())
        item.refresh_from_db()
        self.assertEqual(item.decision_note, 'Approve existing application')
        self.assertEqual(AgentAccessRequest.objects.count(), 1)

    def test_permissions_prerequisites_notes_and_stale_revision_are_checked_by_service(self):
        with self.assertRaises(PermissionDenied):
            grant_agent_qualification(self.user.pk, self.user, 'Self', expected_revision=0)
        with self.assertRaises(ValidationError):
            grant_agent_qualification(self.user.pk, self.reviewer, ' ', expected_revision=0)
        with self.assertRaises(ValidationError):
            grant_agent_qualification(self.user.pk, self.reviewer, 'Wrong module', expected_revision=0, module_key='other')
        self.user.user_permissions.clear()
        with self.assertRaises(ValidationError):
            grant_agent_qualification(self.user.pk, self.reviewer, 'No PAdif capability', expected_revision=0)
        self.assertFalse(AgentQualification.objects.exists())

    def test_stale_management_cannot_reopen_or_revoke_newer_cycle(self):
        grant = grant_agent_qualification(self.user.pk, self.reviewer, 'Initial', expected_revision=0)
        revoke_agent_qualification(self.user.pk, self.reviewer, 'Revoked', expected_revision=grant.revision)
        with self.assertRaises(ValidationError):
            grant_agent_qualification(self.user.pk, self.reviewer, 'Stale reopen', expected_revision=grant.revision)
        grant.refresh_from_db()
        reopened = grant_agent_qualification(self.user.pk, self.reviewer, 'Reopen', expected_revision=grant.revision)
        with self.assertRaises(ValidationError):
            revoke_agent_qualification(self.user.pk, self.reviewer, 'Stale revoke', expected_revision=grant.revision)
        with self.assertRaises(ValidationError):
            update_agent_qualification(self.user.pk, self.reviewer, 'Stale update', expected_revision=grant.revision)
        reopened.refresh_from_db()
        self.assertTrue(reopened.is_active)

    def test_missing_or_forged_target_and_module_do_not_grant(self):
        self.client.force_login(self.reviewer)
        for change in [{'user_id': 'bad'}, {'module_key': 'other'}, {'revision': 'bad'}, {'note': ''}]:
            data={'action':'grant','user_id':self.user.pk,'module_key':'padif','revision':0,'note':'Approved', **change}
            self.client.post('/dashboard/agents/', data, secure=True)
            self.assertFalse(AgentQualification.objects.exists())
        response=self.client.post('/dashboard/agents/', {'action':'grant','user_id':999999999,'module_key':'padif','revision':0,'note':'Missing'}, secure=True)
        self.assertEqual(response.status_code,404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/dashboard/agents/',secure=True).status_code,403)
        self.assertEqual(self.client.post('/dashboard/agents/',{'action':'grant','user_id':self.user.pk,'module_key':'padif','revision':0,'note':'Self'},secure=True).status_code,403)

    def test_csrf_and_get_are_safe_and_notes_are_escaped(self):
        from django.test import Client
        guarded=Client(enforce_csrf_checks=True)
        guarded.force_login(self.reviewer)
        self.assertEqual(guarded.post('/dashboard/agents/',{'action':'grant','user_id':self.user.pk,'module_key':'padif','revision':0,'note':'Approved'},secure=True).status_code,403)
        self.client.force_login(self.reviewer)
        self.client.get('/dashboard/agents/',{'action':'grant','user_id':self.user.pk,'module_key':'padif'},secure=True)
        self.assertFalse(AgentQualification.objects.exists())
        grant_agent_qualification(self.user.pk,self.reviewer,'<script>alert(1)</script>',expected_revision=0)
        page=self.client.get('/dashboard/agents/',{'q':self.user.username},secure=True)
        self.assertNotContains(page,'<script>alert(1)</script>')
        self.assertContains(page,'&lt;script&gt;alert(1)&lt;/script&gt;')
        response = self.client.post('/dashboard/agents/',{'action':'update','user_id':self.user.pk,'module_key':'padif','revision':1,'note':'Safe','q':'https://evil.example/'},secure=True)
        self.assertTrue(response['Location'].startswith('/dashboard/agents/?q='))

    def test_metadata_edit_preserves_article_request_cycle(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from padif.services import create_document_from_upload
        from padif.collaboration import set_collaboration
        from padif.agent_requests import submit_document_requests,decide_document_request
        grant=grant_agent_qualification(self.user.pk,self.reviewer,'Initial',expected_revision=0)
        doc=create_document_from_upload(user=self.reviewer,upload=SimpleUploadedFile('draft.md',b'Private draft'),title='Pending article',commit_message='Initial').document
        set_collaboration(document_id=doc.pk,actor=self.reviewer,username=self.user.username,action='role',role='viewer')
        item=submit_document_requests(self.user,[doc.pk],'Read')[0]
        update_agent_qualification(self.user.pk,self.reviewer,'Metadata only',expected_revision=grant.revision)
        self.assertEqual(decide_document_request(item.pk,self.reviewer,True,'Article approval').status,'approved')
