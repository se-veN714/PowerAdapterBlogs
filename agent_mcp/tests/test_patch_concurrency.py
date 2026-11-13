"""PostgreSQL serialization for exact patch retries, conflicts and live scopes."""
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Event

from django.db import close_old_connections, transaction
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone

from agent_mcp.models import Connection, WriteReceipt
from agent_mcp.tests import test_mcp
from agent_mcp.tools import call_tool
from padif.models import Version
from padif.services import create_branch


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False)
class ConcurrentPatchTests(TransactionTestCase):
    def setUp(self):
        test_mcp.OAuthMcpTests.setUp(self)
        self.connection = Connection.objects.create(user=self.owner, application=self.app, family=uuid.uuid4(),
            scopes=['padif:read', 'padif:version'], expires_at=timezone.now()+timedelta(days=1))
        self.branch = create_branch(document_id=self.document.pk, user=self.owner, name='rewrite', fork_from_version_id=self.head)
        content = Version.objects.get(pk=self.head).content
        self.args = {'document_id': self.document.pk, 'branch': 'rewrite', 'base_version_id': self.head,
            'base_content_sha256': hashlib.sha256(content.encode()).hexdigest(),
            'edits': [{'start_line': 3, 'end_line_exclusive': 4, 'expected_lines': ['First sentence.'], 'replacement_lines': ['A revised sentence.']}],
            'commit_message': 'Concurrent exact edit', 'version_kind': 'patch', 'request_id': 'same'}

    def worker(self, args, entered=None):
        close_old_connections()
        try:
            connection = Connection.objects.get(pk=self.connection.pk)
            if entered:
                entered.set()
            return call_tool(connection, 'apply_version_patch', args)
        finally:
            close_old_connections()

    @skipUnlessDBFeature('has_select_for_update')
    def test_same_request_retries_commit_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, dict(self.args)) for _ in range(2)]
            first, second = [future.result(timeout=15) for future in futures]
        self.assertNotIn('error', first)
        self.assertEqual(first, second)
        self.assertEqual(self.branch.versions.count(), 1)
        self.assertEqual(WriteReceipt.objects.count(), 1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_two_distinct_requests_for_one_base_cannot_overwrite(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, {**self.args, 'request_id': key}) for key in ['first', 'second']]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(sum('error' not in item for item in results), 1)
        self.assertEqual([item['error'] for item in results if 'error' in item], ['STALE_BASE_VERSION'])
        self.assertEqual(self.branch.versions.count(), 1)
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version_id, self.head)

    @skipUnlessDBFeature('has_select_for_update')
    def test_waiting_patch_rechecks_scope_after_acquiring_connection_lock(self):
        entered = Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Connection.objects.select_for_update().get(pk=self.connection.pk)
                pending = pool.submit(self.worker, dict(self.args), entered)
                self.assertTrue(entered.wait(5))
                with self.assertRaises(TimeoutError):
                    pending.result(timeout=.2)
                Connection.objects.filter(pk=self.connection.pk).update(scopes=['padif:read'])
            result = pending.result(timeout=15)
        self.assertEqual(result['error'], 'INSUFFICIENT_SCOPE')
        self.assertEqual(self.branch.versions.count(), 0)
        self.assertFalse(WriteReceipt.objects.exists())
