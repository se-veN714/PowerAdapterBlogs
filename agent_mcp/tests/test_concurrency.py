import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone

from agent_mcp.models import Connection, WriteReceipt
from agent_mcp.tools import call_tool
from padif.models import Branch
from . import test_mcp


@override_settings(PUBLIC_SITE_URL='https://testserver', SESSION_ENGINE='django.contrib.sessions.backends.db',
                   CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class ConcurrentWriteTests(TransactionTestCase):
    setUp = test_mcp.OAuthMcpTests.setUp

    @skipUnlessDBFeature('has_select_for_update')
    def test_two_simultaneous_retries_create_one_branch_and_receipt(self):
        connection = Connection.objects.create(user=self.owner, application=self.app, family=uuid.uuid4(),
                        scopes=['padif:version'], expires_at=timezone.now() + timedelta(days=1))
        args = dict(document_id=self.document.pk, name='concurrent-rewrite', fork_from_version_id=self.head, request_id='same-write')

        def worker():
            close_old_connections()
            try:
                return call_tool(Connection.objects.get(pk=connection.pk), 'create_branch', args)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker), pool.submit(worker)]
            first, second = [future.result(timeout=15) for future in futures]
        self.assertNotIn('error', first)
        self.assertEqual(first, second)
        self.assertEqual(Branch.objects.filter(name='concurrent-rewrite').count(), 1)
        self.assertEqual(WriteReceipt.objects.count(), 1)
