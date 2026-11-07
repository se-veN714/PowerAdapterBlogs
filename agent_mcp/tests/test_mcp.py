import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit, urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application, Grant, RefreshToken

from accounts.agent_auth import approve_device_authorization, create_device_authorization, issue_access_token
from padif.models import Annotation, AnnotationReply, Version, DocumentAgentGrant
from padif.services import create_document_from_upload
from security.models import AuditOutbox
from agent_mcp.models import Connection, WriteReceipt, AgentQualification


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False,
                   SESSION_ENGINE='django.contrib.sessions.backends.db',
                   CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class OAuthMcpTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = get_user_model().objects.create_user(username='mcp-owner', email='mcp@example.test', password='local-test-password', is_active=True)
        self.owner.user_permissions.add(Permission.objects.get(content_type__app_label='padif', codename='use_padif'))
        AgentQualification.objects.create(user=self.owner, is_active=True)
        self.app = Application.objects.create(name='Local Writing Agent', client_id='writing-agent',
                    client_type='public', authorization_grant_type='authorization-code',
                    redirect_uris='http://127.0.0.1:9919/callback', skip_authorization=False)
        self.resource = 'https://testserver/padif/mcp/'
        self.verifier = 'a' * 64
        self.challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b'=').decode()
        self.params = dict(client_id=self.app.client_id, redirect_uri=self.app.redirect_uris,
                           response_type='code', scope='padif:read padif:annotate padif:version', state='test-state',
                           resource=self.resource, code_challenge=self.challenge, code_challenge_method='S256')
        self.document = create_document_from_upload(user=self.owner, upload=SimpleUploadedFile('essay.md', b'# Title\n\nFirst sentence.\n\nNext sentence.'), title='Test Essay', commit_message='Initial').document
        DocumentAgentGrant.objects.create(document=self.document, user=self.owner, granted_by=self.owner, is_enabled=True, allowed_operations=['padif:read', 'padif:annotate', 'padif:version'])
        self.head = self.document.current_version_id

    def authorize(self, scopes=None, allow=True):
        self.client.force_login(self.owner)
        response = self.client.get('/accounts/agent/oauth/authorize/', self.params, secure=True)
        self.assertEqual(response.status_code, 200, response.content[:2000])
        self.assertNotIn('error', response.context)
        form = response.context['form']
        values = {name: form[name].value() or '' for name in form.fields if name != 'allow'}
        values['consent'] = response.context['consent']
        values['approved_scope'] = scopes or self.params['scope'].split()
        if allow:
            values['allow'] = 'true'
        return self.client.post('/accounts/agent/oauth/authorize/', values, secure=True)

    def issue(self, scopes=None):
        response = self.authorize(scopes)
        self.assertEqual(response.status_code, 302, response.content[:1000])
        code = parse_qs(urlsplit(response['Location']).query)['code'][0]
        response = self.client.post('/accounts/agent/oauth/token/', dict(
            grant_type='authorization_code', code=code, client_id=self.app.client_id,
            redirect_uri=self.app.redirect_uris, code_verifier=self.verifier, resource=self.resource), secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def refresh(self, token, **extra):
        return self.client.post('/accounts/agent/oauth/token/', dict(
            grant_type='refresh_token', refresh_token=token, client_id=self.app.client_id,
            resource=self.resource, **extra), secure=True)

    def rpc(self, token, method, params=None, **headers):
        return self.client.post('/padif/mcp/', json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}),
                    content_type='application/json', secure=True,
                    HTTP_AUTHORIZATION='Bearer ' + token,
                    HTTP_ACCEPT='application/json, text/event-stream', **headers)

    def tool(self, token, name, arguments):
        response = self.rpc(token, 'tools/call', {'name': name, 'arguments': arguments})
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertIn('result', data, data)
        return data['result']['structuredContent']

    def test_code_pkce_exchange_hashes_tokens_and_requires_consent(self):
        issued = self.issue(['padif:read'])
        self.assertEqual(issued['expires_in'], 900)
        self.assertEqual(issued['scope'], 'padif:read')
        self.assertEqual(AccessToken.objects.get().token, '')
        self.assertEqual(RefreshToken.objects.get().token, '')
        self.assertEqual(Connection.objects.get().scopes, ['padif:read'])
        self.assertTrue(AuditOutbox.objects.filter(event_type='agent.mcp.authorized').exists())
        self.assertEqual(Grant.objects.count(), 0)

    def test_discovery_https_and_unauthenticated_challenge(self):
        metadata = self.client.get('/.well-known/oauth-authorization-server').json()
        self.assertEqual(metadata['code_challenge_methods_supported'], ['S256'])
        self.assertEqual(metadata['registration_endpoint'], 'https://testserver/accounts/agent/oauth/register/')
        self.assertEqual(self.client.get('/.well-known/oauth-protected-resource/padif/mcp/').json()['resource'], self.resource)
        response = self.rpc('invalid', 'tools/list')
        self.assertEqual(response.status_code, 401)
        self.assertIn('resource_metadata=', response['WWW-Authenticate'])
        self.assertEqual(self.client.post('/accounts/agent/oauth/token/', {}).status_code, 400)

    def test_invalid_pkce_redirect_state_and_resource_are_rejected(self):
        self.client.force_login(self.owner)
        for changed in ({'code_challenge_method': 'plain'}, {'resource': 'https://elsewhere.test/'}, {'state': ''}, {'redirect_uri': 'http://127.0.0.1:9920/callback'}):
            response = self.client.get('/accounts/agent/oauth/authorize/', {**self.params, **changed}, secure=True)
            self.assertNotEqual(response.status_code, 200)
            self.assertEqual(Grant.objects.count(), 0)

    def test_wrong_verifier_and_code_replay(self):
        response = self.authorize(['padif:read'])
        code = parse_qs(urlsplit(response['Location']).query)['code'][0]
        values = dict(grant_type='authorization_code', code=code, client_id=self.app.client_id,
                      redirect_uri=self.app.redirect_uris, code_verifier='b' * 64, resource=self.resource)
        self.assertEqual(self.client.post('/accounts/agent/oauth/token/', values, secure=True).status_code, 400)
        self.assertEqual(Connection.objects.count(), 0)
        values['code_verifier'] = self.verifier
        self.assertEqual(self.client.post('/accounts/agent/oauth/token/', values, secure=True).status_code, 200)
        self.assertEqual(self.client.post('/accounts/agent/oauth/token/', values, secure=True).status_code, 400)

    def test_denied_and_unprivileged_accounts(self):
        response = self.authorize(allow=False)
        self.assertIn('access_denied', response['Location'])
        self.assertEqual(Grant.objects.count(), 0)
        user = get_user_model().objects.create_user(username='no-padif', email='no-padif@example.test', password='test-password', is_active=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/accounts/agent/oauth/authorize/', self.params, secure=True).status_code, 403)

    def test_refresh_rotation_replay_revokes_whole_connection(self):
        original = self.issue()
        rotated = self.refresh(original['refresh_token'])
        self.assertEqual(rotated.status_code, 200, rotated.content)
        self.assertNotEqual(rotated.json()['refresh_token'], original['refresh_token'])
        self.assertEqual(self.refresh(original['refresh_token']).status_code, 400)
        self.assertIsNotNone(Connection.objects.get().revoked_at)
        self.assertEqual(self.rpc(rotated.json()['access_token'], 'tools/list').status_code, 401)
        self.assertEqual(self.refresh(rotated.json()['refresh_token']).status_code, 400)

    def test_scope_narrowing_and_expired_connection(self):
        original = self.issue()
        rotated = self.refresh(original['refresh_token'], scope='padif:read')
        self.assertEqual(rotated.status_code, 200, rotated.content)
        self.assertEqual(Connection.objects.get().scopes, ['padif:read'])
        Connection.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.rpc(rotated.json()['access_token'], 'tools/list').status_code, 401)
        self.assertEqual(self.refresh(rotated.json()['refresh_token']).status_code, 400)

    def test_user_revocation_and_ownership(self):
        issued = self.issue()
        connection = Connection.objects.get()
        other = get_user_model().objects.create_user(username='other-owner', email='other@example.test', password='test-password', is_active=True)
        self.client.force_login(other)
        self.client.post(f'/accounts/agent/oauth/connections/{connection.pk}/revoke/', secure=True)
        self.assertEqual(self.rpc(issued['access_token'], 'tools/list').status_code, 200)
        self.client.force_login(self.owner)
        self.client.post(f'/accounts/agent/oauth/connections/{connection.pk}/revoke/', secure=True)
        self.assertEqual(self.rpc(issued['access_token'], 'tools/list').status_code, 401)
        self.assertEqual(self.refresh(issued['refresh_token']).status_code, 400)

    def test_standard_revoke_and_permission_removal(self):
        issued = self.issue()
        self.owner.user_permissions.clear()
        self.assertEqual(self.rpc(issued['access_token'], 'tools/list').status_code, 401)
        self.assertEqual(self.refresh(issued['refresh_token']).status_code, 400)
        self.owner.user_permissions.add(Permission.objects.get(content_type__app_label='padif', codename='use_padif'))
        response = self.client.post('/accounts/agent/oauth/revoke/', {'client_id': self.app.client_id, 'token': issued['access_token']}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(Connection.objects.get().revoked_at)

    def test_read_only_tool_listing_and_server_scope_checks(self):
        issued = self.issue(['padif:read'])
        token = issued['access_token']
        names = {item['name'] for item in self.rpc(token, 'tools/list').json()['result']['tools']}
        self.assertEqual(names, {'list_documents', 'get_workspace', 'get_version', 'compare_versions', 'list_annotations'})
        self.assertNotIn('publish_branch', names)
        result = self.tool(token, 'commit_version', {})
        self.assertEqual(result['error'], 'INSUFFICIENT_SCOPE')
        self.assertEqual(self.tool(token, 'list_documents', {'query': 'Essay'})['total'], 1)
        result = self.tool(token, 'get_version', {'version_id': self.head, 'start_line': 2, 'end_line': 3})
        self.assertEqual(result['content'], '\nFirst sentence.')
        self.assertEqual(result['total_lines'], 5)
        self.assertEqual(self.client.get('/padif/api/documents/', HTTP_AUTHORIZATION='Bearer ' + token).status_code, 401)

    def test_branch_write_idempotency_stale_base_and_main_unchanged(self):
        token = self.issue()['access_token']
        branch = dict(document_id=self.document.pk, name='rewrite', fork_from_version_id=self.head, request_id='branch-1')
        first = self.tool(token, 'create_branch', branch)
        self.assertEqual(first, self.tool(token, 'create_branch', branch))
        args = dict(document_id=self.document.pk, branch='rewrite', base_version_id=self.head,
                    content='# Revised\n\nNew paragraph.', commit_message='Rewrite opening', version_kind='minor', request_id='commit-1')
        first = self.tool(token, 'commit_version', args)
        self.assertNotIn('error', first, first)
        self.assertEqual(first, self.tool(token, 'commit_version', args))
        self.assertEqual(Version.objects.count(), 2)
        self.assertEqual(self.tool(token, 'commit_version', {**args, 'content': 'Changed'})['error'], 'REQUEST_ID_CONFLICT')
        self.assertEqual(self.tool(token, 'commit_version', {**args, 'request_id': 'commit-2'})['error'], 'STALE_BASE_VERSION')
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version_id, self.head)
        self.assertEqual(WriteReceipt.objects.count(), 2)
        self.assertEqual(self.tool(token, 'commit_version', {**args, 'branch': 'main', 'request_id': 'main-1'})['error'], 'MAIN_REQUIRES_WEB_CONFIRMATION')
        self.assertNotIn('error', self.tool(token, 'get_workspace', {'document_id': self.document.pk, 'branch': 'rewrite'}))
        comparison = self.tool(token, 'compare_versions', {'document_id': self.document.pk, 'from_version': self.head, 'to_version': Version.objects.latest('pk').pk})
        self.assertNotIn('error', comparison)

    def test_annotation_reply_resolution_and_invalid_source_ranges(self):
        token = self.issue()['access_token']
        args = dict(version_id=self.head, kind='question', body='Why?', start_line=3, end_line=3, selected_text='First sentence.', request_id='a1')
        first = self.tool(token, 'add_annotation', args)
        self.assertEqual(first, self.tool(token, 'add_annotation', args))
        annotation = Annotation.objects.get()
        reply = dict(annotation_id=annotation.pk, body='Because.', request_id='r1')
        self.assertEqual(self.tool(token, 'reply_annotation', reply), self.tool(token, 'reply_annotation', reply))
        self.assertEqual(AnnotationReply.objects.count(), 1)
        resolve = dict(annotation_id=annotation.pk, status='resolved', resolution_note='Explained in draft.', request_id='s1')
        self.assertNotIn('error', self.tool(token, 'resolve_annotation', resolve))
        self.assertEqual(self.tool(token, 'list_annotations', {'version_id': self.head, 'status': 'resolved'})['total'], 1)
        self.assertEqual(self.tool(token, 'add_annotation', {**args, 'end_line': 99, 'request_id': 'a2'})['error'], 'INVALID_SOURCE_RANGE')
        self.assertEqual(self.tool(token, 'add_annotation', {**args, 'start_line': True, 'request_id': 'a3'})['error'], 'INVALID_ARGUMENTS')
        self.assertEqual(self.tool(token, 'resolve_annotation', {**resolve, 'resolution_note': ' ', 'request_id': 's2'})['error'], 'RESOLUTION_NOTE_REQUIRED')

    def test_csrf_and_bad_origin(self):
        token = self.issue(['padif:read'])['access_token']
        self.assertEqual(self.rpc(token, 'tools/list', HTTP_ORIGIN='https://evil.test').status_code, 403)
        self.assertEqual(self.rpc(token, 'tools/list', HTTP_MCP_PROTOCOL_VERSION='1900-01-01').status_code, 400)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post('/accounts/agent/oauth/authorize/', self.params, secure=True).status_code, 403)
        self.assertEqual(csrf.post('/accounts/agent/oauth/token/', {'grant_type': 'password'}, secure=True).status_code, 400)

    def test_guide_and_legacy_device_tokens_remain_compatible(self):
        self.client.force_login(self.owner)
        guide = self.client.get('/accounts/security/agents/', secure=True)
        self.assertContains(guide, '复制地址')
        self.assertContains(guide, 'OAuth PKCE')
        self.assertContains(guide, '尚未连接 Agent')
        device = create_device_authorization(client_name='Legacy', scopes=['padif:read'])
        authorization = approve_device_authorization(user=self.owner, user_code=device['user_code'], approve=True)
        token = issue_access_token(authorization=authorization, device_code=device['device_code'])['access_token']
        self.assertEqual(self.client.get('/padif/api/documents/', HTTP_AUTHORIZATION='Bearer ' + token).status_code, 200)
        self.assertEqual(self.rpc(token, 'tools/list').status_code, 401)

    def test_registration_command_rejects_nonlocal_http(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('register_padif_mcp_client', client_id='bad-client', name='Bad', redirect_uri=['http://evil.test/callback'])

    def test_throttling_and_inactive_account(self):
        issued = self.issue()
        with self.settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}):
            from unittest.mock import patch
            with patch('agent_mcp.views.quota', return_value=False):
                response = self.refresh(issued['refresh_token'])
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response['Retry-After'], '60')
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])
        self.assertEqual(self.rpc(issued['access_token'], 'tools/list').status_code, 401)
        self.assertEqual(self.refresh(issued['refresh_token']).status_code, 400)

    def test_tampered_consent_and_expired_code_are_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.get('/accounts/agent/oauth/authorize/', self.params, secure=True)
        form = response.context['form']
        values = {name: form[name].value() or '' for name in form.fields if name != 'allow'}
        values.update(consent=response.context['consent'], allow='true', approved_scope=['padif:read'])
        values['redirect_uri'] = 'http://127.0.0.1:9999/steal'
        self.assertEqual(self.client.post('/accounts/agent/oauth/authorize/', values, secure=True).status_code, 400)
        self.assertEqual(Grant.objects.count(), 0)
        response = self.authorize(['padif:read'])
        code = parse_qs(urlsplit(response['Location']).query)['code'][0]
        Grant.objects.update(expires=timezone.now() - timedelta(seconds=1))
        response = self.client.post('/accounts/agent/oauth/token/', dict(grant_type='authorization_code', code=code,
                    client_id=self.app.client_id, redirect_uri=self.app.redirect_uris, code_verifier=self.verifier, resource=self.resource), secure=True)
        self.assertEqual(response.status_code, 400)

    def test_cleanup_preserves_history_and_live_refreshes(self):
        issued = self.issue()
        call_command('cleanup_padif_mcp', dry_run=True)
        self.assertEqual(self.rpc(issued['access_token'], 'tools/list').status_code, 200)
        Connection.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        call_command('cleanup_padif_mcp')
        self.assertEqual(Connection.objects.count(), 1)
        self.assertEqual(self.refresh(issued['refresh_token']).status_code, 400)

    @override_settings(MFA_ENFORCEMENT_ENABLED=True,
        MFA_TOTP_KEYRING={'mcp-test': base64.urlsafe_b64encode(b'm' * 32).decode()},
        MFA_TOTP_ACTIVE_KEY_ID='mcp-test')
    def test_existing_totp_login_returns_to_oauth_consent(self):
        import pyotp
        from accounts.authn.mfa_services import start_totp_enrollment, confirm_totp_enrollment
        from accounts.models import MfaTotpDevice

        admin = get_user_model().objects.create_superuser(username='mcp-admin', email='mcp-admin@example.test', password='local-test-password')
        enrollment = start_totp_enrollment(user=admin, actor=admin)
        totp = pyotp.parse_uri(enrollment.provisioning_uri)
        confirm_totp_enrollment(user=admin, actor=admin, code=totp.now())
        target = '/accounts/agent/oauth/authorize/?' + urlencode(self.params)
        response = self.client.get(target, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        response = self.client.post('/accounts/login/', {'username': admin.username, 'password': 'local-test-password', 'next': target}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/accounts/security/mfa/challenge/')
        self.assertEqual(Grant.objects.count(), 0)
        device = MfaTotpDevice.objects.get(user=admin)
        code = totp.generate_otp(device.last_accepted_step + 1)
        response = self.client.post('/accounts/security/mfa/challenge/', {'action': 'totp', 'code': code}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], target)
        self.assertContains(self.client.get(target, secure=True), '允许连接')

    def test_admin_revoke_connections_and_staff_boundary(self):
        from agent_mcp.admin import ConnectionAdmin
        from agent_mcp.models import Connection
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from unittest.mock import patch
        issued = self.issue()
        instance = ConnectionAdmin(Connection, AdminSite())
        request = RequestFactory().post('/')
        request.user = self.owner
        self.assertFalse(instance.has_change_permission(request))
        request.user = get_user_model().objects.create_superuser(username='mcp-revoker', email='revoker@example.test', password='test-password')
        with patch('agent_mcp.admin.messages.success'):
            instance.revoke_all_for_users(request, Connection.objects.all())
        self.assertEqual(self.rpc(issued['access_token'], 'tools/list').status_code, 401)
        self.assertEqual(self.refresh(issued['refresh_token']).status_code, 400)
        self.assertTrue(AuditOutbox.objects.filter(event_type='agent.mcp.admin_revoked').exists())

    def test_production_origin_requires_https(self):
        from agent_mcp.checks import check_mcp_origin
        with self.settings(PUBLIC_SITE_URL='http://127.0.0.1:8772', DEBUG=False):
            self.assertEqual(check_mcp_origin(None)[0].id, 'agent_mcp.E001')
        with self.settings(PUBLIC_SITE_URL='http://127.0.0.1:8772', DEBUG=True):
            self.assertEqual(check_mcp_origin(None), [])
        with self.settings(PUBLIC_SITE_URL='https://'):
            self.assertEqual(check_mcp_origin(None)[0].id, 'agent_mcp.E001')
