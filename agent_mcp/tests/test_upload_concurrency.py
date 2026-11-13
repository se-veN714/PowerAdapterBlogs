"""PostgreSQL staging admission and task-unique commit under concurrent requests."""
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings

from agent_mcp.models import Connection, MarkdownUpload
from agent_mcp.tests import test_uploads
from agent_mcp.tools import call_tool
from django.core.files.uploadedfile import SimpleUploadedFile
from padif.models import DocumentAgentGrant
from padif.services import create_document_from_upload, create_branch
import uuid


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class UploadConcurrencyTests(TransactionTestCase):
    setUp = test_uploads.UploadTests.setUp
    call = test_uploads.UploadTests.call
    begin = test_uploads.UploadTests.begin
    append = test_uploads.UploadTests.append
    staged = test_uploads.UploadTests.staged

    def worker(self, name, args, connection_id=None):
        close_old_connections()
        try:
            return call_tool(Connection.objects.get(pk=connection_id or self.connection.pk), name, args)
        finally:
            close_old_connections()

    def test_concurrent_different_commit_request_ids_create_one_version(self):
        upload_id = self.staged(b'# Concurrent\n\nA new paragraph.')
        self.assertNotIn('error', self.call('validate_markdown_upload', {'upload_id': upload_id}))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=15) for future in [pool.submit(self.worker, 'commit_markdown_upload', {
                'upload_id': upload_id, 'commit_message': 'Concurrent', 'version_kind': 'patch', 'request_id': key}) for key in ['first', 'second']]]
        self.assertEqual(results[0], results[1])
        self.assertNotIn('error', results[0])
        self.assertEqual(self.branch.versions.count(), 1)

    def test_concurrent_begin_reserves_three_slots_not_four(self):
        self.begin()
        self.begin()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=15) for future in [pool.submit(self.worker, 'begin_markdown_upload', {
                'document_id': self.document.pk, 'branch': 'upload', 'base_version_id': self.head,
                'request_id': key}) for key in ['first', 'second']]]
        self.assertEqual(sum('error' not in item for item in results), 1)
        self.assertEqual([item['error'] for item in results if 'error' in item], ['UPLOAD_QUOTA_EXCEEDED'])
        self.assertEqual(MarkdownUpload.objects.filter(state='awaiting_file').count(), 3)

    def test_user_admission_serializes_across_different_connections_and_documents(self):
        self.begin()
        self.begin()
        second = create_document_from_upload(user=self.owner, upload=SimpleUploadedFile('other.md', b'# Other'), title='Other', commit_message='Initial').document
        DocumentAgentGrant.objects.create(document=second, user=self.owner, granted_by=self.owner,
            is_enabled=True, allowed_operations=self.connection.scopes)
        create_branch(document_id=second.pk, user=self.owner, name='upload', fork_from_version_id=second.current_version_id)
        other = Connection.objects.create(user=self.owner, application=self.app, family=uuid.uuid4(),
            scopes=self.connection.scopes, expires_at=self.connection.expires_at)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, 'begin_markdown_upload', {
                'document_id': document.pk, 'branch': 'upload', 'base_version_id': document.current_version_id,
                'request_id': 'cross-connection'}, connection_id) for document, connection_id in
                [(self.document, self.connection.pk), (second, other.pk)]]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(sum('error' not in item for item in results), 1)
        self.assertEqual([item['error'] for item in results if 'error' in item], ['UPLOAD_QUOTA_EXCEEDED'])
