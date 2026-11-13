"""Private staging state, integrity, authorization and atomic version commits."""
import base64
import hashlib
import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.test import RequestFactory
from django.utils import timezone

from agent_mcp.models import Connection, MarkdownUpload, MarkdownUploadChunk, WriteReceipt
from agent_mcp.tests import test_mcp
from agent_mcp.tools import call_tool, BY_NAME
from agent_mcp.tool_safety import ToolFailure
from agent_mcp import uploads
from agent_mcp.transport import endpoint
from padif.models import DocumentAgentGrant, Version
from padif.services import create_branch


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False,
    SESSION_ENGINE='django.contrib.sessions.backends.db',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class UploadTests(TestCase):
    def setUp(self):
        test_mcp.OAuthMcpTests.setUp(self)
        self.connection = Connection.objects.create(user=self.owner, application=self.app, family=uuid.uuid4(),
            scopes=['padif:read', 'padif:annotate', 'padif:version'], expires_at=timezone.now()+timedelta(days=1))
        self.branch = create_branch(document_id=self.document.pk, user=self.owner, name='upload', fork_from_version_id=self.head)
        self.serial = 0

    def call(self, name, args, connection=None):
        self.serial += 1
        if not BY_NAME[name]['annotations']['readOnlyHint']:
            args = {'request_id': 'upload-test-'+str(self.serial), **args}
        return call_tool(connection or self.connection, name, args)

    def begin(self, data=None, **extra):
        args = {'document_id': self.document.pk, 'branch': 'upload', 'base_version_id': self.head, **extra}
        if data is not None:
            args.update(file_name='essay.md', file_size=len(data), file_sha256=hashlib.sha256(data).hexdigest())
        return self.call('begin_markdown_upload', args)

    def append(self, upload_id, data, index=0, **extra):
        return self.call('append_markdown_chunk', {'upload_id': upload_id, 'chunk_index': index,
            'data_base64': base64.b64encode(data).decode(), 'chunk_sha256': hashlib.sha256(data).hexdigest(), **extra})

    def staged(self, data):
        result = self.begin(data)
        self.assertNotIn('error', result)
        upload_id = result['upload_id']
        for index, start in enumerate(range(0, len(data), 16384)):
            self.assertNotIn('error', self.append(upload_id, data[start:start+16384], index))
        return upload_id

    def test_canonical_validation_diff_chunk_read_and_commit_once_main_unchanged(self):
        data = '\ufeff# 稿件\r\n\r\n第一句🙂。\r\n\r\n```sh\r\necho token\r\n```\r\n'.encode('utf-8')
        upload_id = self.staged(data)
        validated = self.call('validate_markdown_upload', {'upload_id': upload_id})
        self.assertNotIn('error', validated)
        canonical = data.decode('utf-8').lstrip('\ufeff').replace('\r\n', '\n')
        self.assertEqual(validated['content_sha256'], hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual(validated['file_sha256'], hashlib.sha256(data).hexdigest())
        self.assertNotIn('error', self.call('compare_versions', validated['diff_ref']['arguments']))
        read = self.call('read_content_chunk', {'source_kind': 'upload_markdown', 'source_id': upload_id})
        self.assertEqual(read['content'], canonical)
        args = {'upload_id': upload_id, 'commit_message': 'Private upload', 'version_kind': 'patch'}
        before = Version.objects.count()
        first = self.call('commit_markdown_upload', args)
        self.assertNotIn('error', first)
        self.assertEqual(self.call('commit_markdown_upload', args), first)
        self.assertEqual(Version.objects.count(), before+1)
        self.assertEqual(Version.objects.get(pk=first['version']['id']).content, canonical)
        self.assertEqual(self.call('cancel_markdown_upload', {'upload_id': upload_id})['error'], 'UPLOAD_ALREADY_COMMITTED')
        self.assertFalse(MarkdownUploadChunk.objects.filter(upload_id=upload_id).exists())

        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version_id, self.head)

    def test_awaiting_manifest_page_owner_csrf_and_frozen_binding(self):
        result = self.begin()
        self.assertEqual(result['state'], 'awaiting_file')
        task = MarkdownUpload.objects.get(pk=result['upload_id'])
        self.assertEqual(task.reserved_bytes, 2097152)
        url = result['file_page_url'].removeprefix('https://testserver')
        web = Client(enforce_csrf_checks=True)
        self.assertEqual(web.get(url, secure=True).status_code, 302)
        web.force_login(self.owner)
        self.assertEqual(web.get(url, secure=True).status_code, 200)
        manifest = {'action': 'manifest', 'file_name': '稿.md', 'file_size': 3, 'file_sha256': hashlib.sha256(b'abc').hexdigest()}
        self.assertEqual(web.post(url, manifest, content_type='application/json', secure=True).status_code, 403)
        import json
        headers = {'HTTP_X_CSRFTOKEN': web.cookies['csrftoken'].value, 'HTTP_REFERER': 'https://testserver'+url}
        response = web.post(url, json.dumps(manifest), content_type='application/json', secure=True, **headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(web.post(url, json.dumps({**manifest, 'file_name': 'other.md'}), content_type='application/json', secure=True, **headers).json()['error'], 'MANIFEST_CONFLICT')
        other = type(self.owner).objects.create_user(username='other-upload', email='other@example.test', password='local', is_active=True)
        web.force_login(other)
        self.assertEqual(web.get(url, secure=True).status_code, 404)

    def test_out_of_order_duplicate_conflict_missing_and_freeze(self):
        data = b'a'*16384+b'b'*17
        upload_id = self.begin(data)['upload_id']
        self.assertNotIn('error', self.append(upload_id, data[16384:], 1))
        self.assertEqual(self.call('validate_markdown_upload', {'upload_id': upload_id})['error'], 'UPLOAD_INCOMPLETE')
        self.assertNotIn('error', self.append(upload_id, data[16384:], 1))
        self.assertEqual(self.append(upload_id, b'c'*17, 1)['error'], 'CHUNK_CONFLICT')
        self.assertEqual(self.append(upload_id, b'a', 2)['error'], 'INVALID_CHUNK')
        self.assertNotIn('error', self.append(upload_id, data[:16384]))
        self.assertNotIn('error', self.call('validate_markdown_upload', {'upload_id': upload_id}))
        self.assertEqual(self.append(upload_id, data[:16384])['error'], 'UPLOAD_STATE_CONFLICT')

    def test_format_hash_failure_purges_and_keeps_versions(self):
        for data in [b'\xff\xfe', b'MZ\x00exe', b'PK\x03\x04zip', b'hello\x00world', b'%PDF-1.7 binary', b'   \n']:
            with self.subTest(data=data[:10]):
                upload_id = self.staged(data)
                result = self.call('validate_markdown_upload', {'upload_id': upload_id})
                self.assertIn('error', result)
                task = MarkdownUpload.objects.get(pk=upload_id)
                self.assertEqual(task.state, 'invalidated')
                self.assertFalse(task.chunks.exists())
        cache.clear()
        upload_id = self.staged(b'hello')
        MarkdownUpload.objects.filter(pk=upload_id).update(file_sha256='0'*64)
        self.assertEqual(self.call('validate_markdown_upload', {'upload_id': upload_id})['error'], 'FILE_INTEGRITY_FAILED')
        self.assertEqual(Version.objects.count(), 1)

    def test_filename_quotas_cancellation_and_expiry_cleanup(self):
        for name in ['../secret.md', 'C:\\key.md', 'bad\x01.md', 'a.exe', 'a'*121+'.md']:
            args = {'document_id': self.document.pk, 'branch': 'upload', 'base_version_id': self.head,
                'file_name': name, 'file_size': 2, 'file_sha256': hashlib.sha256(b'ok').hexdigest()}
            self.assertIn(self.call('begin_markdown_upload', args)['error'], ('INVALID_FILE_NAME', 'INVALID_ARGUMENTS'))
        cache.clear()
        ids = [self.begin()['upload_id'] for _ in range(3)]
        self.assertEqual(self.begin()['error'], 'UPLOAD_QUOTA_EXCEEDED')
        for _ in range(2):
            self.assertNotIn('error', self.call('cancel_markdown_upload', {'upload_id': ids[0]}))
        MarkdownUpload.objects.filter(pk=ids[1]).update(expires_at=timezone.now()-timedelta(seconds=1))
        call_command('cleanup_padif_mcp', stdout=StringIO())
        self.assertEqual(MarkdownUpload.objects.get(pk=ids[1]).state, 'expired')
        self.assertNotIn('error', self.begin())

    def test_new_connection_and_revoked_or_reopened_article_cannot_reuse_staging(self):
        upload_id = self.staged(b'# Private\n')
        other = Connection.objects.create(user=self.owner, application=self.app, family=uuid.uuid4(),
            scopes=self.connection.scopes, expires_at=self.connection.expires_at)
        self.assertEqual(self.call('get_markdown_upload_status', {'upload_id': upload_id}, other)['error'], 'NOT_FOUND')
        grant = DocumentAgentGrant.objects.get(document=self.document)
        grant.is_enabled = False
        grant.save()
        self.assertEqual(self.call('get_markdown_upload_status', {'upload_id': upload_id})['error'], 'DOCUMENT_PERMISSION_DENIED')
        grant.is_enabled, grant.revision = True, grant.revision+1
        grant.save()
        self.assertEqual(self.call('get_markdown_upload_status', {'upload_id': upload_id})['error'], 'UPLOAD_AUTHORIZATION_CHANGED')

    def test_commit_audit_failure_rolls_back_task_version_and_receipt(self):
        upload_id = self.staged(b'# Private\n')
        self.assertNotIn('error', self.call('validate_markdown_upload', {'upload_id': upload_id}))
        before = WriteReceipt.objects.count()
        with patch('agent_mcp.uploads.audit_upload', side_effect=RuntimeError('Audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.call('commit_markdown_upload', {'upload_id': upload_id, 'commit_message': 'QA', 'version_kind': 'patch'})
        task = MarkdownUpload.objects.get(pk=upload_id)
        self.assertEqual(task.state, 'validated')
        self.assertTrue(task.chunks.exists())
        self.assertEqual(Version.objects.count(), 1)
        self.assertEqual(WriteReceipt.objects.count(), before)

    def test_stale_base_archival_global_capacity_rate_and_expiry_cannot_commit(self):
        self.assertEqual(self.begin(branch='main')['error'], 'MAIN_REQUIRES_WEB_CONFIRMATION')
        upload_id = self.staged(b'# One')
        self.assertNotIn('error', self.call('validate_markdown_upload', {'upload_id': upload_id}))
        self.branch.archived_at = timezone.now()
        self.branch.save()
        self.assertEqual(self.call('commit_markdown_upload', {'upload_id': upload_id, 'commit_message': 'QA', 'version_kind': 'patch'})['error'], 'STALE_BASE_VERSION')
        self.assertEqual(MarkdownUpload.objects.get(pk=upload_id).state, 'invalidated')
        self.branch.archived_at = None
        self.branch.save()
        with override_settings(MCP_UPLOAD_MAX_ACTIVE=0):
            self.assertEqual(self.begin()['error'], 'UPLOAD_CAPACITY_EXCEEDED')
        with patch('agent_mcp.uploads.rate', side_effect=ToolFailure('RATE_LIMITED')):
            self.assertEqual(self.begin()['error'], 'RATE_LIMITED')
        upload_id = self.staged(b'# Expired')
        MarkdownUpload.objects.filter(pk=upload_id).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.call('validate_markdown_upload', {'upload_id': upload_id})['error'], 'UPLOAD_EXPIRED')
        self.assertFalse(MarkdownUploadChunk.objects.filter(upload_id=upload_id).exists())

    def test_all_six_tools_keep_scope_article_permissions_and_storage_failure_rolls_back(self):
        data = b'# Private'
        task = self.begin(data)
        upload_id = task['upload_id']
        cases = {
            'begin_markdown_upload': {'document_id': self.document.pk, 'branch': 'upload', 'base_version_id': self.head},
            'append_markdown_chunk': {'upload_id': upload_id, 'chunk_index': 0, 'data_base64': base64.b64encode(data).decode(), 'chunk_sha256': hashlib.sha256(data).hexdigest()},
            'get_markdown_upload_status': {'upload_id': upload_id},
            'validate_markdown_upload': {'upload_id': upload_id},
            'commit_markdown_upload': {'upload_id': upload_id, 'commit_message': 'QA', 'version_kind': 'patch'},
            'cancel_markdown_upload': {'upload_id': upload_id},
        }
        Connection.objects.filter(pk=self.connection.pk).update(scopes=['padif:read'])
        for name, args in cases.items():
            self.assertEqual(self.call(name, args)['error'], 'INSUFFICIENT_SCOPE', name)
        Connection.objects.filter(pk=self.connection.pk).update(scopes=self.connection.scopes)
        DocumentAgentGrant.objects.filter(document=self.document).update(is_enabled=False)
        for name, args in cases.items():
            self.assertEqual(self.call(name, args)['error'], 'DOCUMENT_PERMISSION_DENIED', name)
        DocumentAgentGrant.objects.filter(document=self.document).update(is_enabled=True)
        before = WriteReceipt.objects.count()
        with patch('agent_mcp.uploads.MarkdownUploadChunk.objects.create', side_effect=OSError('Storage unavailable')):
            with self.assertRaises(OSError):
                self.append(upload_id, data)
        self.assertFalse(MarkdownUploadChunk.objects.filter(upload_id=upload_id).exists())
        self.assertEqual(WriteReceipt.objects.count(), before)
        self.assertEqual(MarkdownUpload.objects.get(pk=upload_id).state, 'receiving')
        self.assertNotIn('error', self.append(upload_id, data))

    def test_connection_chunk_rate_limit_uses_shared_counter(self):
        for _ in range(60):
            uploads.rate(self.connection, 'append', 60)
        with self.assertRaises(ToolFailure) as failure:
            uploads.rate(self.connection, 'append', 60)
        self.assertEqual(failure.exception.code, 'RATE_LIMITED')

    def test_commit_corruption_and_chunk_receipt_cannot_reopen_frozen_upload(self):
        data = b'# Validated'
        upload_id = self.staged(data)
        self.call('validate_markdown_upload', {'upload_id': upload_id})
        chunk = MarkdownUploadChunk.objects.get(upload_id=upload_id)
        chunk.data = b'! Changed!'
        chunk.save()
        result = self.call('commit_markdown_upload', {'upload_id': upload_id, 'commit_message': 'QA', 'version_kind': 'patch'})
        self.assertEqual(result['error'], 'FILE_INTEGRITY_FAILED')
        self.assertEqual(MarkdownUpload.objects.get(pk=upload_id).state, 'invalidated')
        self.assertFalse(MarkdownUploadChunk.objects.filter(upload_id=upload_id).exists())


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False,
    SESSION_ENGINE='django.contrib.sessions.backends.db',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class UploadTransportBudgetTests(TestCase):
    setUp = test_mcp.OAuthMcpTests.setUp
    authorize = test_mcp.OAuthMcpTests.authorize
    issue = test_mcp.OAuthMcpTests.issue
    rpc = test_mcp.OAuthMcpTests.rpc

    def test_large_transport_is_rejected_before_read_and_new_chunk_has_small_budget(self):
        token = self.issue()['access_token']
        request = RequestFactory().post('/padif/mcp/', b'x'*2300001, content_type='application/json', secure=True,
            HTTP_AUTHORIZATION='Bearer '+token, HTTP_ACCEPT='application/json, text/event-stream')
        with patch.object(request, 'read', side_effect=AssertionError('Oversized body must not be read')):
            self.assertEqual(endpoint(request).status_code, 413)
        response = self.rpc(token, 'tools/call', {'name': 'append_markdown_chunk', 'arguments': {
            'upload_id': str(uuid.uuid4()), 'request_id': 'large-block', 'chunk_index': 0,
            'data_base64': 'a'*70000, 'chunk_sha256': '0'*64}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result']['structuredContent']['error'], 'CONTENT_TOO_LARGE')
