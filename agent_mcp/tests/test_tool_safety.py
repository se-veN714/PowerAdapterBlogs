"""Every existing tool must recheck live authority before exposing data or receipts."""
import uuid
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from agent_mcp.models import Connection, WriteReceipt
from agent_mcp.tests import test_mcp
from agent_mcp.tools import call_tool
from padif.models import Annotation, DocumentAgentGrant


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False)
class ToolSafetyTests(TestCase):
    setUp = test_mcp.OAuthMcpTests.setUp

    def connection(self):
        return Connection.objects.create(user=self.owner, application=self.app, family=uuid.uuid4(),
            scopes=['padif:read', 'padif:annotate', 'padif:version'], expires_at=timezone.now()+timedelta(days=1))

    def calls(self):
        note = Annotation.objects.create(version_id=self.head, author=self.owner, kind='question',
            body='Private text', start_line=1, end_line=1)
        return {
            'list_documents': {},
            'get_workspace': {'document_id': self.document.pk},
            'get_version': {'version_id': self.head},
            'compare_versions': {'document_id': self.document.pk, 'from_version': self.head, 'to_version': self.head},
            'list_annotations': {'version_id': self.head},
            'create_branch': {'document_id': self.document.pk, 'name': 'safety', 'fork_from_version_id': self.head, 'request_id': 'branch'},
            'commit_version': {'document_id': self.document.pk, 'branch': 'main', 'base_version_id': self.head,
                'content': 'No main writes', 'commit_message': 'Invalid', 'version_kind': 'patch', 'request_id': 'commit'},
            'add_annotation': {'version_id': self.head, 'kind': 'question', 'body': 'Question', 'start_line': 1, 'end_line': 1, 'request_id': 'note'},
            'reply_annotation': {'annotation_id': note.pk, 'body': 'Reply', 'request_id': 'reply'},
            'resolve_annotation': {'annotation_id': note.pk, 'status': 'resolved', 'resolution_note': 'Reviewed', 'request_id': 'resolve'},
        }

    def test_all_ten_tools_reject_a_stale_object_after_connection_revocation(self):
        connection = self.connection()
        Connection.objects.filter(pk=connection.pk).update(revoked_at=timezone.now())
        for name, args in self.calls().items():
            with self.subTest(tool=name):
                self.assertEqual(call_tool(connection, name, args).get('error'), 'INVALID_TOKEN')
        self.assertFalse(WriteReceipt.objects.exists())

    def test_all_ten_tools_recheck_current_scopes_not_caller_cached_scopes(self):
        connection = self.connection()
        Connection.objects.filter(pk=connection.pk).update(scopes=[])
        for name, args in self.calls().items():
            with self.subTest(tool=name):
                self.assertEqual(call_tool(connection, name, args).get('error'), 'INSUFFICIENT_SCOPE')

    def test_receipt_cannot_restore_access_after_article_downgrade(self):
        connection = self.connection()
        args = {'document_id': self.document.pk, 'name': 'receipt-branch', 'fork_from_version_id': self.head, 'request_id': 'saved'}
        first = call_tool(connection, 'create_branch', args)
        self.assertNotIn('error', first)
        DocumentAgentGrant.objects.filter(user=self.owner).update(allowed_operations=['padif:read'])
        self.assertEqual(call_tool(connection, 'create_branch', args)['error'], 'DOCUMENT_PERMISSION_DENIED')
        self.assertEqual(WriteReceipt.objects.count(), 1)

    def test_expired_connections_and_disabled_accounts_cannot_use_any_tool(self):
        connection = self.connection()
        calls = self.calls()
        Connection.objects.filter(pk=connection.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        for name, args in calls.items():
            self.assertEqual(call_tool(connection, name, args)['error'], 'INVALID_TOKEN', name)
        Connection.objects.filter(pk=connection.pk).update(expires_at=timezone.now()+timedelta(days=1))
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])
        for name, args in calls.items():
            self.assertEqual(call_tool(connection, name, args)['error'], 'INVALID_TOKEN', name)

    def test_oversized_success_response_rolls_back_annotation_and_receipt(self):
        connection = self.connection()
        before = Annotation.objects.count()
        result = call_tool(connection, 'add_annotation', {'version_id': self.head, 'kind': 'question',
            'body': '🙂'*10000, 'start_line': 1, 'end_line': 1, 'request_id': 'large-response'})
        self.assertEqual(result['error'], 'OUTPUT_TOO_LARGE')
        self.assertEqual(Annotation.objects.count(), before)
        self.assertFalse(WriteReceipt.objects.exists())

    def test_audit_failure_rolls_back_branch_and_success_receipt(self):
        from unittest.mock import patch
        connection = self.connection()
        with patch('agent_mcp.tools.audit', side_effect=RuntimeError('Test audit unavailable')):
            with self.assertRaises(RuntimeError):
                call_tool(connection, 'create_branch', {'document_id': self.document.pk, 'name': 'no-audit',
                    'fork_from_version_id': self.head, 'request_id': 'no-audit'})
        self.assertFalse(self.document.branches.filter(name='no-audit').exists())
        self.assertFalse(WriteReceipt.objects.exists())


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False,
                   SESSION_ENGINE='django.contrib.sessions.backends.db',
                   CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class BoundedTransportTests(TestCase):
    setUp = test_mcp.OAuthMcpTests.setUp
    authorize = test_mcp.OAuthMcpTests.authorize
    issue = test_mcp.OAuthMcpTests.issue
    rpc = test_mcp.OAuthMcpTests.rpc

    def test_wire_budget_and_exact_control_character_source_roundtrip(self):
        from padif.models import Version
        content = '文🙂\\"\x01\n'*4000
        Version.objects.filter(pk=self.head).update(content=content)
        token = self.issue()['access_token']
        args = {'source_kind': 'version_markdown', 'source_id': self.head}
        chunks = []
        while True:
            response = self.rpc(token, 'tools/call', {'name': 'read_content_chunk', 'arguments': args})
            self.assertEqual(response.status_code, 200)
            self.assertLessEqual(len(response.content), 64*1024)
            result = response.json()['result']['structuredContent']
            self.assertNotIn('error', result)
            chunks.append(result['content'])
            if not result['next_cursor']:
                break
            self.assertGreater(result['end_byte_exclusive'], result['start_byte'])
            args['cursor'] = result['next_cursor']
        self.assertEqual(''.join(chunks), content)
        response = self.rpc(token, 'tools/call', {'name': 'get_workspace', 'arguments': {'document_id': self.document.pk}})
        self.assertLessEqual(len(response.content), 64*1024)
        self.assertEqual(response.json()['result']['structuredContent']['error'], 'OUTPUT_TOO_LARGE')
