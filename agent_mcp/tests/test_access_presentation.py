import base64
import hashlib

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from oauth2_provider.models import Application

from agent_mcp.presentation import portal_context
from padif.tests import test_agent_requests
from padif.agent_requests import submit_document_requests, decide_document_request
from padif.collaboration import set_collaboration
from padif.services import create_document_from_upload


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False,
                   SESSION_ENGINE='django.contrib.sessions.backends.db')
class AgentAccessPresentationTests(TestCase):
    setUp = test_agent_requests.ArticleAgentRequestTests.setUp

    def test_summary_separates_approved_pending_and_requestable_articles(self):
        approved = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        decide_document_request(approved.pk, self.owner, True, 'Approved')
        for name in ['Pending one', 'Pending two', 'Pending three']:
            document = create_document_from_upload(user=self.owner, upload=SimpleUploadedFile('draft.md', b'Draft'), title=name, commit_message='Initial').document
            set_collaboration(document_id=document.pk, actor=self.owner, username=self.user.username, action='role', role='viewer')
            submit_document_requests(self.user, [document.pk], 'Read')
        context = portal_context(self.user)
        self.assertEqual(context['agent_article_count'], 1)
        self.assertEqual(context['agent_pending_article_count'], 3)
        self.assertEqual(context['agent_requestable_count'], 0)
        self.client.force_login(self.user)
        response = self.client.get('/accounts/security/agents/', secure=True)
        self.assertContains(response, '已授权 <strong data-granted-count>1</strong> 篇', html=False)
        self.assertContains(response, '待审核 <strong data-pending-count>3</strong> 篇', html=False)

    def test_oauth_shows_only_ai_articles_and_explains_scope_does_not_upgrade_viewer(self):
        approved = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        decide_document_request(approved.pk, self.owner, True, 'Approved')
        hidden = create_document_from_upload(user=self.owner, upload=SimpleUploadedFile('hidden.md', b'Secret'), title='Hidden unrelated article', commit_message='Initial').document
        app = Application.objects.create(name='WorkBuddy', client_type='public', authorization_grant_type='authorization-code', redirect_uris='http://127.0.0.1:9919/callback')
        challenge = base64.urlsafe_b64encode(hashlib.sha256(b'a' * 64).digest()).rstrip(b'=').decode()
        self.client.force_login(self.user)
        response = self.client.get('/accounts/agent/oauth/authorize/', {'client_id': app.client_id,
            'redirect_uri': app.redirect_uris, 'response_type': 'code', 'state': 'ui-test',
            'code_challenge': challenge, 'code_challenge_method': 'S256',
            'scope': 'padif:read padif:annotate padif:version', 'resource': 'https://testserver/padif/mcp/'}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['consent_article_count'], 1)
        self.assertEqual(response.context['consent_writable_count'], 0)
        self.assertContains(response, self.document.title)
        self.assertNotContains(response, hidden.title)
        self.assertContains(response, 'name="approved_scope"', count=3)
        self.assertContains(response, '下面是操作类型，不是文章数量')
        self.assertContains(response, '勾选写入操作，不会提升文章角色或逐篇 AI+ 权限')
