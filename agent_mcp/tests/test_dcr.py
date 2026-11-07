import json

from django.test import TestCase, override_settings
from oauth2_provider.models import Application, AccessToken
from agent_mcp.models import Connection
from . import test_mcp


@override_settings(PUBLIC_SITE_URL='https://testserver', SESSION_ENGINE='django.contrib.sessions.backends.db',
                   CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class DynamicRegistrationTests(TestCase):
    setUp = test_mcp.OAuthMcpTests.setUp
    authorize = test_mcp.OAuthMcpTests.authorize
    issue = test_mcp.OAuthMcpTests.issue
    rpc = test_mcp.OAuthMcpTests.rpc

    def register(self, **overrides):
        metadata = {'client_name': 'WorkBuddy', 'redirect_uris': ['http://127.0.0.1:45678/callback'],
                    'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
                    'token_endpoint_auth_method': 'none'}
        return self.client.post('/accounts/agent/oauth/register/', json.dumps({**metadata, **overrides}),
                                content_type='application/json', secure=True)

    def test_client_without_preconfigured_id_can_discover_and_register(self):
        discovery = self.client.get('/.well-known/oauth-authorization-server').json()
        self.assertEqual(discovery.get('registration_endpoint'), 'https://testserver/accounts/agent/oauth/register/')
        result = self.register()
        self.assertEqual(result.status_code, 201, result.content)
        data = result.json()
        app = Application.objects.get(client_id=data['client_id'])
        self.assertEqual(app.client_type, 'public')
        self.assertFalse(app.skip_authorization)
        self.assertEqual(app.registration_source, 'dcr')
        self.assertNotIn('client_secret', data)
        self.assertNotIn('access_token', data)
        self.assertEqual(Connection.objects.count(), 0)
        self.assertEqual(AccessToken.objects.count(), 0)

    def test_registered_client_uses_existing_consent_pkce_and_scopes(self):
        result = self.register()
        self.assertEqual(result.status_code, 201, result.content)
        self.app = Application.objects.get(client_id=result.json()['client_id'])
        self.params.update(client_id=self.app.client_id, redirect_uri=self.app.redirect_uris)
        issued = self.issue(['padif:read'])
        listed = self.rpc(issued['access_token'], 'tools/list')
        self.assertEqual(listed.status_code, 200, listed.content)
        names = {tool['name'] for tool in listed.json()['result']['tools']}
        self.assertEqual(len(names), 5)
        self.assertNotIn('commit_version', names)
        self.assertNotIn('publish_branch', names)

    def test_unsafe_redirects_and_grants_are_rejected(self):
        from django.core.cache import cache
        for value in ['http://example.test/callback', 'javascript:alert(1)', 'https://example.test/cb#fragment',
                      'http://127.0.0.1.evil.test/callback', 'https://user:pass@example.test/callback', 'https://*.example.test/cb']:
            cache.clear()
            self.assertEqual(self.register(redirect_uris=[value]).status_code, 400, value)
        for changed in ({'grant_types': ['client_credentials']}, {'response_types': ['token']},
                        {'token_endpoint_auth_method': 'client_secret_basic'}, {'scope': 'admin'},
                        {'redirect_uris': []}, {'client_name': ['bad']}):
            cache.clear()
            self.assertEqual(self.register(**changed).status_code, 400, changed)

    def test_dynamic_registration_is_limited_and_untrusted_fields_cannot_grant_access(self):
        from unittest.mock import patch
        with patch('agent_mcp.views.quota', return_value=False):
            self.assertEqual(self.register().status_code, 429)
        response = self.register(skip_authorization=True, user=self.owner.pk, client_type='confidential')
        self.assertEqual(response.status_code, 201)
        app = Application.objects.get(client_id=response.json()['client_id'])
        self.assertIsNone(app.user_id)
        self.assertFalse(app.skip_authorization)
        self.assertEqual(app.client_type, 'public')
