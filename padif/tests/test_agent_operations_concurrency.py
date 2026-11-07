from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from unittest import skipUnless
from django.core.exceptions import ValidationError
from django.db import connection, close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from padif.tests import test_collaboration
from padif.models import Document, DocumentAgentGrant
from padif.agent_requests import adjust_document_operations, decide_document_request
from agent_mcp.tools import call_tool

@skipUnless(connection.vendor == 'postgresql', 'Row locks require PostgreSQL')
@override_settings(MFA_ENFORCEMENT_ENABLED=False, PUBLIC_SITE_URL='https://testserver')
class OperationConcurrencyTests(TransactionTestCase):
    setUp = test_collaboration.DocumentCollaborationTests.setUp
    user = test_collaboration.DocumentCollaborationTests.user
    make_document = test_collaboration.DocumentCollaborationTests.make_document
    change = test_collaboration.DocumentCollaborationTests.change
    connection = test_collaboration.DocumentCollaborationTests.connection

    def waiting(self, action, during):
        entered = Event()
        def worker():
            close_old_connections()
            try:
                entered.set()
                return action()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Document.objects.select_for_update().get(pk=self.document.pk)
                result = pool.submit(worker)
                self.assertTrue(entered.wait(5))
                with self.assertRaises(TimeoutError):
                    result.result(timeout=.2)
                during()
            return result.result(timeout=10)

    def test_waiting_tool_rechecks_specific_operation_after_downgrade(self):
        self.change(self.writer, 'ai', enabled=True)
        connection = self.connection(self.writer)
        grant = DocumentAgentGrant.objects.get(document=self.document, user=self.writer)
        result = self.waiting(lambda: call_tool(connection, 'create_branch', {'document_id': self.document.pk,
            'name': 'must-not-save', 'fork_from_version_id': self.head.pk, 'request_id': 'waiting-version'}),
            lambda: adjust_document_operations(self.document.pk, self.writer, ['padif:read'], grant.revision, 'No versions'))
        self.assertEqual(result.get('error'), 'DOCUMENT_PERMISSION_DENIED')
        self.assertFalse(self.document.branches.filter(name='must-not-save').exists())

    def test_waiting_approval_cannot_restore_reduced_permissions(self):
        self.change(self.writer, 'ai', enabled=True, operations=['padif:read', 'padif:annotate'])
        grant = DocumentAgentGrant.objects.get(document=self.document, user=self.writer)
        item = adjust_document_operations(self.document.pk, self.writer, ['padif:read', 'padif:annotate', 'padif:version'], grant.revision, 'Version request')
        def approve():
            try:
                return decide_document_request(item.pk, self.owner, True, 'Approve').status
            except ValidationError:
                return 'already-invalidated'
        result = self.waiting(approve, lambda: adjust_document_operations(self.document.pk, self.writer, ['padif:read'], grant.revision, 'Withdraw annotation'))
        self.assertEqual(result, 'already-invalidated')
        grant.refresh_from_db()
        self.assertEqual(grant.allowed_operations, ['padif:read'])
