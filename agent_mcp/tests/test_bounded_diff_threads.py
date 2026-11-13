"""MCP diff isolation and authorized, snapshot-bound reply pagination."""
import subprocess
import time
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from agent_mcp.models import Connection
from agent_mcp.tests import test_mcp
from agent_mcp.tools import call_tool
from padif import api
from padif.models import Annotation, AnnotationReply, DocumentAgentGrant, Version


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False)
class BoundedDiffThreadTests(TestCase):
    setUp = test_mcp.OAuthMcpTests.setUp

    def connection(self):
        return Connection.objects.create(user=self.owner, application=self.app, family=uuid.uuid4(),
            scopes=['padif:read', 'padif:annotate', 'padif:version'], expires_at=timezone.now()+timedelta(days=1))

    def note(self, **kwargs):
        return Annotation.objects.create(version_id=self.head, author=self.owner, kind='question',
            start_line=1, end_line=1, body='Question?', **kwargs)

    def test_reply_pages_preserve_snapshot_author_time_and_connection_binding(self):
        note = self.note()
        replies = [AnnotationReply.objects.create(annotation=note, author=self.owner, body=f'Answer {i}') for i in range(6)]
        connection = self.connection()
        args = {'version_id': self.head, 'paginate_replies': True, 'reply_limit': 2}
        first = call_tool(connection, 'list_annotations', args)['items'][0]
        self.assertEqual([reply['id'] for reply in first['replies']], [r.pk for r in replies[:2]])
        self.assertFalse(first['replies_complete'])
        AnnotationReply.objects.create(annotation=note, author=self.owner, body='Later reply outside snapshot')
        cursor = first['next_reply_cursor']
        found = list(first['replies'])
        while cursor:
            result = call_tool(connection, 'list_annotations', {**args, 'reply_annotation_id': note.pk, 'reply_cursor': cursor})
            self.assertNotIn('error', result)
            found.extend(result['items'])
            cursor = result['next_reply_cursor']
        self.assertEqual([reply['id'] for reply in found], [r.pk for r in replies])
        self.assertEqual(found[0]['author'], self.owner.username)
        self.assertEqual(found[0]['created_at'], replies[0].created_at.isoformat())
        result = call_tool(self.connection(), 'list_annotations', {**args, 'reply_annotation_id': note.pk, 'reply_cursor': first['next_reply_cursor']})
        self.assertEqual(result['error'], 'INVALID_CURSOR')

    def test_large_reply_body_and_resolution_note_have_readable_references(self):
        note = self.note(resolution_note='解释🙂' * 8000)
        reply = AnnotationReply.objects.create(annotation=note, author=self.owner, body='回答🙂' * 8000)
        connection = self.connection()
        result = call_tool(connection, 'list_annotations', {'version_id': self.head, 'paginate_replies': True})
        item = result['items'][0]
        self.assertFalse(item['resolution_note_complete'])
        self.assertFalse(item['replies'][0]['body_complete'])
        self.assertEqual(item['replies'][0]['body_ref']['source_id'], reply.pk)
        ref = item['replies'][0]['body_ref']
        content = []
        args = {'source_kind': ref['source_kind'], 'source_id': ref['source_id']}
        while True:
            part = call_tool(connection, 'read_content_chunk', args)
            self.assertNotIn('error', part)
            content.append(part['content'])
            if not part['next_cursor']:
                break
            args['cursor'] = part['next_cursor']
        self.assertEqual(''.join(content), reply.body)

    def test_reply_cursor_does_not_bypass_version_or_revocation(self):
        note = self.note()
        for index in range(3):
            AnnotationReply.objects.create(annotation=note, author=self.owner, body=str(index))
        connection = self.connection()
        args = {'version_id': self.head, 'paginate_replies': True, 'reply_limit': 1}
        first = call_tool(connection, 'list_annotations', args)['items'][0]
        other = self.note()
        resumed = {**args, 'reply_annotation_id': other.pk, 'reply_cursor': first['next_reply_cursor']}
        self.assertEqual(call_tool(connection, 'list_annotations', resumed)['error'], 'INVALID_CURSOR')
        resumed['reply_annotation_id'] = note.pk
        Connection.objects.filter(pk=connection.pk).update(scopes=[])
        self.assertEqual(call_tool(connection, 'list_annotations', resumed)['error'], 'INSUFFICIENT_SCOPE')

    def test_small_legacy_thread_keeps_shape_and_oversized_legacy_has_recovery(self):
        note = self.note()
        reply = AnnotationReply.objects.create(annotation=note, author=self.owner, body='Small answer')
        connection = self.connection()
        result = call_tool(connection, 'list_annotations', {'version_id': self.head})
        self.assertEqual(result['items'][0]['replies'][0]['body'], reply.body)
        AnnotationReply.objects.filter(pk=reply.pk).update(body='大🙂' * 10000)
        result = call_tool(connection, 'list_annotations', {'version_id': self.head})
        self.assertEqual(result['error'], 'OUTPUT_TOO_LARGE')
        self.assertIn('paginate_replies', result['recovery'])

    def diff_args(self, content):
        original = Version.objects.get(pk=self.head)
        original.pk = None
        original.content = content
        original.semantic_version = f'1.0.{self.document.versions.count()}'
        original.save()
        return {'document_id': self.document.pk, 'from_version': self.head, 'to_version': original.pk}

    def test_diff_pages_match_legacy_complete_ops_and_global_stats(self):
        args = self.diff_args('# Title\n\nChanged sentence.\n\nNext sentence.')
        connection = self.connection()
        legacy = call_tool(connection, 'compare_versions', args)['diff']
        self.assertEqual(legacy, api._diff_payload(Version.objects.get(pk=self.head), Version.objects.get(pk=args['to_version'])))
        ops = []
        offset = 0
        while offset is not None:
            result = call_tool(connection, 'compare_versions', {**args, 'offset': offset, 'limit': 1})
            self.assertNotIn('error', result)
            page = result['diff']
            self.assertEqual(page['stats'], legacy['stats'])
            self.assertEqual(page['from_version']['id'], self.head)
            ops.extend(page['ops'])
            offset = page['next_offset']
        self.assertEqual(ops, legacy['ops'])

    def test_diff_complexity_is_rejected_before_spawning(self):
        args = self.diff_args('重复。' * 4000)
        Version.objects.filter(pk=self.head).update(content='重复。' * 4000)
        with patch('agent_mcp.bounded_diff.subprocess.run') as run:
            result = call_tool(self.connection(), 'compare_versions', args)
        self.assertEqual(result['error'], 'DIFF_TOO_COMPLEX')
        run.assert_not_called()

    def test_diff_size_sentence_and_character_preflight_budgets(self):
        for old, new in [
            ('Short.', 'x'*(2*1024*1024+1)),
            ('Short.', '句。'*10001),
            ('a'*2100, 'b'*2100),
        ]:
            with self.subTest(old_size=len(old), new_size=len(new)):
                Version.objects.filter(pk=self.head).update(content=old)
                args = self.diff_args(new)
                with patch('agent_mcp.bounded_diff.subprocess.run') as run:
                    result = call_tool(self.connection(), 'compare_versions', args)
                self.assertEqual(result['error'], 'DIFF_TOO_COMPLEX')
                run.assert_not_called()

    def test_diff_timeout_has_no_partial_success(self):
        args = self.diff_args('Different.')
        with patch('agent_mcp.bounded_diff.subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 3)) as run:
            result = call_tool(self.connection(), 'compare_versions', args)
        self.assertEqual(result['error'], 'DIFF_TOO_COMPLEX')
        self.assertNotIn('diff', result)
        self.assertGreater(run.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(run.call_args.kwargs['timeout'], 3)

    def test_real_worker_timeout_reaps_child_and_releases_capacity(self):
        args = self.diff_args('Different.')
        connection = self.connection()
        children = []
        popen = subprocess.Popen

        def record_child(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child

        started = time.monotonic()
        with patch('agent_mcp.bounded_diff.DIFF_TIMEOUT_SECONDS', .02), patch('subprocess.Popen', side_effect=record_child):
            result = call_tool(connection, 'compare_versions', args)
        self.assertEqual(result['error'], 'DIFF_TOO_COMPLEX')
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertLess(time.monotonic()-started, 2)
        self.assertNotIn('error', call_tool(connection, 'compare_versions', args))

    def test_busy_worker_rejects_without_spawning_and_failure_has_safe_error(self):
        args = self.diff_args('Different.')
        with patch('agent_mcp.bounded_diff._WORKERS') as workers, patch('agent_mcp.bounded_diff.subprocess.run') as run:
            workers.acquire.return_value = False
            self.assertEqual(call_tool(self.connection(), 'compare_versions', args)['error'], 'DIFF_BUSY')
            run.assert_not_called()
        with patch('agent_mcp.bounded_diff.subprocess.run', side_effect=OSError('SECRET/PATH')):
            result = call_tool(self.connection(), 'compare_versions', args)
        self.assertEqual(result['error'], 'DIFF_WORKER_UNAVAILABLE')
        self.assertNotIn('SECRET', str(result))

    def test_cross_document_diff_and_reply_version_mismatch_are_hidden(self):
        args = self.diff_args('Different.')
        connection = self.connection()
        args['from_version'] = 99999999
        self.assertEqual(call_tool(connection, 'compare_versions', args)['error'], 'NOT_FOUND')
        note = self.note()
        result = call_tool(connection, 'list_annotations', {'version_id': args['to_version'], 'reply_annotation_id': note.pk})
        self.assertEqual(result['error'], 'NOT_FOUND')

    def test_reply_cursor_expiry_tampering_and_article_revocation(self):
        note = self.note()
        for index in range(3):
            AnnotationReply.objects.create(annotation=note, author=self.owner, body=str(index))
        connection = self.connection()
        args = {'version_id': self.head, 'paginate_replies': True, 'reply_limit': 1}
        first = call_tool(connection, 'list_annotations', args)['items'][0]
        args.update(reply_annotation_id=note.pk, reply_cursor=first['next_reply_cursor'])
        with patch('django.core.signing.time.time', return_value=time.time()+3602):
            self.assertEqual(call_tool(connection, 'list_annotations', args)['error'], 'INVALID_CURSOR')
        self.assertEqual(call_tool(connection, 'list_annotations', {**args, 'reply_cursor': 'bad'})['error'], 'INVALID_CURSOR')
        DocumentAgentGrant.objects.filter(document=self.document).update(is_enabled=False)
        self.assertEqual(call_tool(connection, 'list_annotations', args)['error'], 'DOCUMENT_PERMISSION_DENIED')

    def test_large_single_diff_item_exposes_source_reference(self):
        args = self.diff_args(Version.objects.get(pk=self.head).content + '\n\n' + '新增🙂' * 5000)
        result = call_tool(self.connection(), 'compare_versions', {**args, 'offset': 0, 'limit': 100})
        self.assertNotIn('error', result)
        insert = next(op for op in result['diff']['ops'] if op['op'] == 'insert')
        self.assertFalse(insert['text_complete'])
        self.assertEqual(insert['text_ref']['source_id'], args['to_version'])


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False,
    SESSION_ENGINE='django.contrib.sessions.backends.db',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class BoundedPageTransportTests(TestCase):
    setUp = test_mcp.OAuthMcpTests.setUp
    authorize = test_mcp.OAuthMcpTests.authorize
    issue = test_mcp.OAuthMcpTests.issue
    rpc = test_mcp.OAuthMcpTests.rpc

    def test_actual_diff_wire_pages_preserve_all_ops_under_budget(self):
        old = Version.objects.get(pk=self.head)
        new = Version.objects.get(pk=self.head)
        new.pk = None
        new.content = '\n'.join(str(index) + ('"\\\x01'*100) + '。' for index in range(150))
        new.semantic_version = '1.0.1'
        new.save()
        expected = api._diff_payload(old, new)['ops']
        token = self.issue(['padif:read'])['access_token']
        found, offset = [], 0
        while offset is not None:
            response = self.rpc(token, 'tools/call', {'name': 'compare_versions', 'arguments': {
                'document_id': self.document.pk, 'from_version': old.pk, 'to_version': new.pk,
                'offset': offset, 'limit': 100}})
            self.assertEqual(response.status_code, 200)
            self.assertLessEqual(len(response.content), 65536)
            value = response.json()['result']['structuredContent']
            self.assertNotIn('error', value)
            page = value['diff']
            found.extend(page['ops'])
            offset = page['next_offset']
        self.assertEqual(found, expected)
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version_id, self.head)

    def test_wire_bounded_annotation_and_reply_pages_never_skip_items(self):
        notes = [Annotation.objects.create(version_id=self.head, author=self.owner, kind='question',
            start_line=1, end_line=1, body='"\\\x01'*200, resolution_note='"\\\x01'*200) for _ in range(12)]
        replies = []
        for note in notes:
            replies.extend(AnnotationReply.objects.bulk_create([AnnotationReply(annotation=note, author=self.owner,
                body='"\\\x01'*200) for _ in range(25)]))
        token = self.issue(['padif:read'])['access_token']

        def call(args):
            response = self.rpc(token, 'tools/call', {'name': 'list_annotations', 'arguments': args})
            self.assertEqual(response.status_code, 200)
            self.assertLessEqual(len(response.content), 65536)
            value = response.json()['result']['structuredContent']
            self.assertNotIn('error', value)
            return value

        found, offset = [], 0
        while offset is not None:
            result = call({'version_id': self.head, 'limit': 100, 'offset': offset, 'paginate_replies': True})
            found.extend(item['id'] for item in result['items'])
            offset = result['next_offset']
        self.assertEqual(found, [note.pk for note in notes])
        found, cursor = [], None
        while True:
            args = {'version_id': self.head, 'reply_annotation_id': notes[0].pk, 'reply_limit': 100}
            if cursor:
                args['reply_cursor'] = cursor
            result = call(args)
            found.extend(item['id'] for item in result['items'])
            cursor = result['next_reply_cursor']
            if not cursor:
                break
        self.assertEqual(found, [reply.pk for reply in replies if reply.annotation_id == notes[0].pk])
