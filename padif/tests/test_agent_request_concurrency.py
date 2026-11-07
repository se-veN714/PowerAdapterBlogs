from concurrent.futures import ThreadPoolExecutor
from threading import Event, Barrier
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import connection, transaction, close_old_connections
from django.test import TransactionTestCase

from agent_mcp.access import lock_identity, revoke_agent_qualification
from accounts.agent_auth import create_device_authorization, approve_device_authorization, issue_access_token
from padif.agent_requests import submit_document_requests, decide_document_request
from padif.models import Document, DocumentAgentGrant, DocumentAgentRequest
from padif.tests import test_agent_requests


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL locks required')
class ArticleRequestConcurrencyTests(TransactionTestCase):
    setUp = test_agent_requests.ArticleAgentRequestTests.setUp

    def run_isolated(self, action):
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '5s'")
                return action()
        finally:
            close_old_connections()

    def test_approval_and_qualification_revocation_do_not_deadlock_or_restore_ai(self):
        item = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        doc_locked, user_locked, proceed = Event(), Event(), Event()

        def approve():
            Document.objects.select_for_update().get(pk=self.document.pk)
            doc_locked.set()
            self.assertTrue(proceed.wait(10))
            return decide_document_request(item.pk, self.owner, True, 'Approve').status

        def revoke():
            self.assertTrue(doc_locked.wait(10))
            lock_identity(self.user.pk)
            user_locked.set()
            revoke_agent_qualification(self.user.pk, self.owner, 'Revoke')

        with ThreadPoolExecutor(max_workers=2) as pool:
            approval = pool.submit(self.run_isolated, approve)
            revocation = pool.submit(self.run_isolated, revoke)
            try:
                self.assertTrue(user_locked.wait(10))
            finally:
                proceed.set()
            self.assertEqual(approval.result(timeout=15), 'approved')
            revocation.result(timeout=15)
        self.assertFalse(DocumentAgentGrant.objects.get(user=self.user, document=self.document).is_enabled)

    def test_competing_article_decisions_only_produce_one_terminal_result(self):
        item = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        barrier = Barrier(2)

        def decide(approve):
            barrier.wait(10)
            try:
                return decide_document_request(item.pk, self.owner, approve, 'Decision').status
            except ValidationError:
                return 'already-final'

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda choice: self.run_isolated(lambda: decide(choice)), [True, False]))
        self.assertEqual(results.count('already-final'), 1)
        item.refresh_from_db()
        self.assertIn(item.status, ['approved', 'rejected'])
        self.assertEqual(DocumentAgentGrant.objects.filter(user=self.user, is_enabled=True).exists(), item.status == 'approved')

    def test_legacy_token_exchange_waits_for_revocation_and_cannot_issue_after_it(self):
        device = create_device_authorization(client_name='Concurrent device', scopes=['padif:read'])
        approved = approve_device_authorization(user=self.user, user_code=device['user_code'], approve=True)
        user_locked, proceed = Event(), Event()

        def revoke():
            lock_identity(self.user.pk)
            user_locked.set()
            self.assertTrue(proceed.wait(10))
            revoke_agent_qualification(self.user.pk, self.owner, 'Revoke')

        def exchange():
            self.assertTrue(user_locked.wait(10))
            return issue_access_token(authorization=approved, device_code=device['device_code'])

        with ThreadPoolExecutor(max_workers=2) as pool:
            revocation = pool.submit(self.run_isolated, revoke)
            self.assertTrue(user_locked.wait(10))
            issued = pool.submit(self.run_isolated, exchange)
            proceed.set()
            revocation.result(timeout=15)
            self.assertIsNone(issued.result(timeout=15))
        self.assertEqual(DocumentAgentRequest.objects.count(), 0)
