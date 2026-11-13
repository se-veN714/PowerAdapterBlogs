"""Bounded source reads and exact, atomic branch patches."""
import hashlib
import uuid
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from agent_mcp.models import Connection, WriteReceipt
from agent_mcp.tests import test_mcp
from agent_mcp.tools import call_tool
from padif.models import Annotation, Version
from padif.services import create_branch


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False)
class LongDocumentTests(TestCase):
    setUp = test_mcp.OAuthMcpTests.setUp

    def connection(self):
        return Connection.objects.create(user=self.owner, application=self.app, family=uuid.uuid4(),
            scopes=['padif:read', 'padif:annotate', 'padif:version'], expires_at=timezone.now()+timedelta(days=1))

    def hash(self, content):
        return hashlib.sha256(content.encode()).hexdigest()

    def test_summary_has_no_body_and_outline_ignores_fenced_headings(self):
        content = '# 序章\n\n正文\n```md\n# Not a heading\n```\n\n## 第二节\n'
        Version.objects.filter(pk=self.head).update(content=content)
        connection = self.connection()
        result = call_tool(connection, 'get_workspace', {'document_id': self.document.pk, 'include_content': False})
        self.assertNotIn('error', result)
        self.assertNotIn('content', result['current_version'])
        self.assertEqual(result['current_version']['content_sha256'], self.hash(content))
        outline = call_tool(connection, 'get_document_outline', {'document_id': self.document.pk})
        self.assertNotIn('error', outline)
        self.assertEqual([item['line'] for item in outline['items']], [1, 8])

    def test_long_line_roundtrips_in_chunks_and_rejects_tampered_cursor(self):
        content = '# 序章\n\n' + '中文🙂\\"' * 7000 + '\n\n'
        Version.objects.filter(pk=self.head).update(content=content)
        connection = self.connection()
        args = {'source_kind': 'version_markdown', 'source_id': self.head}
        chunks = []
        while True:
            result = call_tool(connection, 'read_content_chunk', args)
            self.assertNotIn('error', result)
            chunks.append(result['content'])
            if not result['next_cursor']:
                break
            args['cursor'] = result['next_cursor']
        self.assertEqual(''.join(chunks), content)
        args['cursor'] = 'bad-cursor'
        self.assertEqual(call_tool(connection, 'read_content_chunk', args)['error'], 'INVALID_CURSOR')

    def patch_args(self, content, **changes):
        return {'document_id': self.document.pk, 'branch': 'rewrite', 'base_version_id': self.head,
                'base_content_sha256': self.hash(content), 'edits': [{'start_line': 3, 'end_line_exclusive': 4,
                    'expected_lines': ['First sentence.'], 'replacement_lines': ['改写第一句。']}],
                'commit_message': 'Exact edit', 'version_kind': 'patch', 'request_id': 'exact-patch', **changes}

    def test_patch_preserves_blank_lines_and_main_and_is_idempotent(self):
        content = Version.objects.get(pk=self.head).content
        branch = create_branch(document_id=self.document.pk, user=self.owner, name='rewrite', fork_from_version_id=self.head)
        connection = self.connection()
        args = self.patch_args(content)
        result = call_tool(connection, 'apply_version_patch', args)
        self.assertNotIn('error', result)
        updated = Version.objects.get(pk=result['version']['id'])
        self.assertEqual(updated.content, '# Title\n\n改写第一句。\n\nNext sentence.')
        self.assertEqual(updated.branch_id, branch.pk)
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version_id, self.head)
        self.assertEqual(call_tool(connection, 'apply_version_patch', args), result)
        self.assertEqual(WriteReceipt.objects.count(), 1)

    def test_bad_second_patch_rolls_back_and_wrong_hash_or_main_never_writes(self):
        content = Version.objects.get(pk=self.head).content
        create_branch(document_id=self.document.pk, user=self.owner, name='rewrite', fork_from_version_id=self.head)
        connection = self.connection()
        args = self.patch_args(content)
        args['edits'].append({'start_line': 5, 'end_line_exclusive': 6, 'expected_lines': ['Wrong old text'], 'replacement_lines': ['Bad']})
        before = Version.objects.count()
        self.assertEqual(call_tool(connection, 'apply_version_patch', args)['error'], 'PATCH_SOURCE_MISMATCH')
        self.assertEqual(Version.objects.count(), before)
        self.assertFalse(WriteReceipt.objects.exists())
        self.assertEqual(call_tool(connection, 'apply_version_patch', self.patch_args(content, base_content_sha256='0'*64))['error'], 'PATCH_BASE_MISMATCH')
        self.assertEqual(call_tool(connection, 'apply_version_patch', self.patch_args(content, branch='main'))['error'], 'MAIN_REQUIRES_WEB_CONFIRMATION')

    def test_annotation_and_mutable_note_chunks_pin_content(self):
        note = Annotation.objects.create(version_id=self.head, author=self.owner, kind='question', body='提问🙂'*12000,
            start_line=1, end_line=1, resolution_note='说明'*15000)
        connection = self.connection()
        args = {'source_kind': 'resolution_note', 'source_id': note.pk}
        first = call_tool(connection, 'read_content_chunk', args)
        self.assertNotIn('error', first)
        self.assertTrue(first['next_cursor'])
        Annotation.objects.filter(pk=note.pk).update(resolution_note='Changed')
        self.assertEqual(call_tool(connection, 'read_content_chunk', {**args, 'cursor': first['next_cursor']})['error'], 'STALE_CONTENT')

    def test_patch_insert_delete_blank_eof_and_bom_crlf_normalization(self):
        raw = '\ufeff# Title\r\n\r\nFirst sentence.\r\n\r\nNext sentence.\r\n'
        Version.objects.filter(pk=self.head).update(content=raw)
        canonical = '# Title\n\nFirst sentence.\n\nNext sentence.\n'
        create_branch(document_id=self.document.pk, user=self.owner, name='rewrite', fork_from_version_id=self.head)
        edits = [
            {'start_line': 3, 'end_line_exclusive': 4, 'expected_lines': ['First sentence.'], 'replacement_lines': []},
            {'start_line': 6, 'end_line_exclusive': 6, 'expected_lines': [], 'replacement_lines': ['末尾新句。']},
        ]
        result = call_tool(self.connection(), 'apply_version_patch', self.patch_args(canonical, edits=edits))
        self.assertNotIn('error', result)
        self.assertEqual(Version.objects.get(pk=result['version']['id']).content, '# Title\n\n\nNext sentence.\n末尾新句。\n')
        self.assertEqual(Version.objects.get(pk=self.head).content, raw)

    def test_overlaps_newlines_stale_heads_and_forged_cursors_are_rejected(self):
        content = Version.objects.get(pk=self.head).content
        create_branch(document_id=self.document.pk, user=self.owner, name='rewrite', fork_from_version_id=self.head)
        connection = self.connection()
        args = self.patch_args(content)
        args['edits'].append(dict(args['edits'][0]))
        self.assertEqual(call_tool(connection, 'apply_version_patch', args)['error'], 'PATCH_OVERLAP')
        args = self.patch_args(content)
        args['edits'][0]['replacement_lines'] = ['Unexpected\n']
        self.assertEqual(call_tool(connection, 'apply_version_patch', args)['error'], 'INVALID_ARGUMENTS')
        result = call_tool(connection, 'apply_version_patch', self.patch_args(content))
        self.assertNotIn('error', result)
        self.assertEqual(call_tool(connection, 'apply_version_patch', self.patch_args(content, request_id='new-attempt'))['error'], 'STALE_BASE_VERSION')
        Version.objects.filter(pk=self.head).update(content='文'*30000)
        first = call_tool(connection, 'read_content_chunk', {'source_kind': 'version_markdown', 'source_id': self.head})
        other = self.connection()
        self.assertEqual(call_tool(other, 'read_content_chunk', {'source_kind': 'version_markdown', 'source_id': self.head, 'cursor': first['next_cursor']})['error'], 'INVALID_CURSOR')

    def test_huge_requests_and_cursor_paths_and_sensitive_extra_fields_are_rejected(self):
        connection = self.connection()
        for extra in [{'path': 'C:/secret.key'}, {'token': 'DO-NOT-ECHO'}, {'version_id': True}]:
            result = call_tool(connection, 'get_document_outline', {'document_id': self.document.pk, **extra})
            self.assertEqual(result['error'], 'INVALID_ARGUMENTS')
            self.assertNotIn('DO-NOT-ECHO', str(result))
        content = Version.objects.get(pk=self.head).content
        create_branch(document_id=self.document.pk, user=self.owner, name='rewrite', fork_from_version_id=self.head)
        args = self.patch_args(content)
        args['edits'][0]['replacement_lines'] = ['文'*30000]
        self.assertEqual(call_tool(connection, 'apply_version_patch', args)['error'], 'CONTENT_TOO_LARGE')

    def test_other_document_sources_and_versions_never_leak_metadata(self):
        from django.contrib.auth import get_user_model
        from django.core.files.uploadedfile import SimpleUploadedFile
        from padif.services import create_document_from_upload
        stranger = get_user_model().objects.create_superuser(username='private-source-owner', email='private-source@example.test', password='local')
        other = create_document_from_upload(user=stranger, upload=SimpleUploadedFile('private.md', b'# DO-NOT-LEAK'), title='Private', commit_message='Initial').document
        connection = self.connection()
        note = Annotation.objects.create(version_id=other.current_version_id, author=stranger, kind='question',
            body='DO-NOT-LEAK', start_line=1, end_line=1)
        for name, args in [
            ('get_document_outline', {'document_id': other.pk}),
            ('get_document_outline', {'document_id': self.document.pk, 'version_id': other.current_version_id}),
            ('read_content_chunk', {'source_kind': 'version_markdown', 'source_id': other.current_version_id}),
            ('read_content_chunk', {'source_kind': 'annotation_body', 'source_id': note.pk}),
        ]:
            result = call_tool(connection, name, args)
            self.assertEqual(result['error'], 'NOT_FOUND')
            self.assertNotIn('DO-NOT-LEAK', str(result))

    def test_chunk_cursor_keeps_original_version_after_branch_advances(self):
        content = '# Title\n\n' + '原文🙂' * 2000
        Version.objects.filter(pk=self.head).update(content=content)
        create_branch(document_id=self.document.pk, user=self.owner, name='rewrite', fork_from_version_id=self.head)
        connection = self.connection()
        args = {'source_kind': 'version_markdown', 'source_id': self.head, 'max_bytes': 1024}
        first = call_tool(connection, 'read_content_chunk', args)
        patched = call_tool(connection, 'apply_version_patch', self.patch_args(content, edits=[
            {'start_line': 1, 'end_line_exclusive': 2, 'expected_lines': ['# Title'], 'replacement_lines': ['# Updated']},
        ]))
        self.assertNotIn('error', patched)
        chunks = [first['content']]
        cursor = first['next_cursor']
        while cursor:
            chunk = call_tool(connection, 'read_content_chunk', {**args, 'cursor': cursor})
            self.assertNotIn('error', chunk)
            self.assertEqual(chunk['content_sha256'], first['content_sha256'])
            chunks.append(chunk['content'])
            cursor = chunk['next_cursor']
        self.assertEqual(''.join(chunks), content)

    def test_actual_nul_is_rejected_but_literal_escape_is_preserved(self):
        connection = self.connection()
        args = {'version_id': self.head, 'kind': 'question', 'body': 'bad\x00text',
                'start_line': 1, 'end_line': 1, 'request_id': 'nul-check'}
        self.assertEqual(call_tool(connection, 'add_annotation', args)['error'], 'INVALID_ARGUMENTS')
        self.assertFalse(Annotation.objects.exists())
        args['body'] = r'Literal \u0000 example'
        result = call_tool(connection, 'add_annotation', args)
        self.assertNotIn('error', result)
        self.assertEqual(Annotation.objects.get(pk=result['annotation']['id']).body, args['body'])
