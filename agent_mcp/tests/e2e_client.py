"""Real official-SDK OAuth + Streamable HTTP acceptance; local QA only.

Run through browser_oauth.cjs: tokens stay in memory; the browser supplies the
authorization callback via a per-run ignored directory. Only the named local
fixture document is modified, always on a new writing branch.
"""
import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata


async def main():
    base = os.environ.get('PADIF_MCP_QA_BASE', 'http://127.0.0.1:8772')
    if urlsplit(base).hostname not in {'localhost', '127.0.0.1'}:
        raise RuntimeError('Local QA hosts only')
    exchange = Path(os.environ['PADIF_MCP_QA_EXCHANGE_DIR'])
    metadata = OAuthClientMetadata(client_name='Local Writing Agent', redirect_uris=['http://127.0.0.1:9919/callback'],
                                   grant_types=['authorization_code', 'refresh_token'], response_types=['code'],
                                   token_endpoint_auth_method='none', scope='padif:read padif:annotate padif:version')

    class MemoryStorage:
        tokens = None
        client_info = None if os.environ.get('PADIF_MCP_QA_DCR') == '1' else OAuthClientInformationFull(**metadata.model_dump(), client_id='padif-local-writing-agent')

        async def get_tokens(self):
            return self.tokens

        async def set_tokens(self, tokens):
            self.tokens = tokens

        async def get_client_info(self):
            return self.client_info

        async def set_client_info(self, client_info):
            self.client_info = client_info

    storage = MemoryStorage()

    async def redirect(url):
        (exchange / 'authorize.json').write_text(json.dumps({'url': url}), encoding='utf-8')

    async def callback():
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if (exchange / 'callback.json').exists():
                value = json.loads((exchange / 'callback.json').read_text(encoding='utf-8'))
                return value['code'], value['state']
            await asyncio.sleep(.2)
        raise RuntimeError('Browser authorization callback timed out')

    auth = OAuthClientProvider(base + '/padif/mcp/', metadata, storage, redirect_handler=redirect, callback_handler=callback)
    async with httpx.AsyncClient(auth=auth, timeout=120, trust_env=False) as http:
        async with streamable_http_client(base + '/padif/mcp/', http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == 'padif-writing'
                listed = await session.list_tools()
                assert len(listed.tools) == 19
                assert not any('publish' in item.name for item in listed.tools)

                async def call(name, args):
                    result = await session.call_tool(name, args)
                    assert not result.isError, result.content
                    return result.structuredContent

                docs = await call('list_documents', {'query': os.environ.get('PADIF_MCP_QA_TITLE', 'MCP 本地验收')})
                assert docs['total'] == 1
                doc_id = docs['items'][0]['id']
                workspace = await call('get_workspace', {'document_id': doc_id, 'include_content': False})
                head = workspace['current_version']['id']
                outline = await call('get_document_outline', {'document_id': doc_id})
                assert outline['version']['id'] == head
                source = await call('read_content_chunk', {'source_kind': 'version_markdown', 'source_id': head})
                assert source['content_sha256'] == workspace['current_version']['content_sha256']
                branch_name = 'sdk-' + uuid.uuid4().hex[:8]
                branch_args = dict(document_id=doc_id, name=branch_name, fork_from_version_id=head, request_id='create-branch')
                assert await call('create_branch', branch_args) == await call('create_branch', branch_args)
                args = dict(document_id=doc_id, branch=branch_name, base_version_id=head,
                            content='# Revised\n\nA local QA paragraph.\n\nAnother paragraph.',
                            commit_message='Official SDK local acceptance', version_kind='patch', request_id='commit')
                result = await call('commit_version', args)
                assert result == await call('commit_version', args)
                workspace = await call('get_workspace', {'document_id': doc_id, 'branch': branch_name})
                version_id = workspace['current_version']['id']
                version = await call('get_version', {'version_id': version_id, 'start_line': 2, 'end_line': 3})
                assert version['content'] == '\nA local QA paragraph.'
                annotation = await call('add_annotation', dict(version_id=version_id, kind='question', body='Local QA question', start_line=3, end_line=3, request_id='annotation'))
                annotation_id = annotation['annotation']['id']
                await call('reply_annotation', dict(annotation_id=annotation_id, body='Local QA answer', request_id='reply'))
                await call('reply_annotation', dict(annotation_id=annotation_id, body='Second local QA answer', request_id='reply-second'))
                await call('resolve_annotation', dict(annotation_id=annotation_id, status='resolved', resolution_note='Verified locally.', request_id='resolve'))
                assert (await call('list_annotations', dict(version_id=version_id, status='resolved')))['total'] == 1
                full_diff = (await call('compare_versions', dict(document_id=doc_id, from_version=head, to_version=version_id)))['diff']
                offset, ops = 0, []
                while offset is not None:
                    page = (await call('compare_versions', dict(document_id=doc_id, from_version=head, to_version=version_id, offset=offset, limit=1)))['diff']
                    assert page['stats'] == full_diff['stats']
                    ops.extend(page['ops'])
                    offset = page['next_offset']
                assert ops == full_diff['ops']
                note = (await call('list_annotations', dict(version_id=version_id, paginate_replies=True, reply_limit=1)))['items'][0]
                assert note['replies_total'] == 2 and not note['replies_complete']
                next_replies = await call('list_annotations', dict(version_id=version_id,
                    reply_annotation_id=annotation_id, reply_cursor=note['next_reply_cursor'], reply_limit=1))
                assert next_replies['items'][0]['body'] == 'Second local QA answer'
                assert next_replies['next_reply_cursor'] is None
                assert (await call('get_workspace', {'document_id': doc_id}))['current_version']['id'] == head
                patch_outline = await call('get_document_outline', {'document_id': doc_id, 'version_id': version_id})
                patch_args = dict(document_id=doc_id, branch=branch_name, base_version_id=version_id,
                    base_content_sha256=patch_outline['version']['content_sha256'], edits=[
                        {'start_line': 3, 'end_line_exclusive': 4, 'expected_lines': ['A local QA paragraph.'],
                         'replacement_lines': ['An exact local SDK edit.']}], commit_message='Official SDK exact patch',
                    version_kind='patch', request_id='exact-patch')
                patched = await call('apply_version_patch', patch_args)
                assert await call('apply_version_patch', patch_args) == patched
                assert (await call('get_version', {'version_id': patched['version']['id']}))['content'] == '# Revised\n\nAn exact local SDK edit.\n\nAnother paragraph.'
                if os.environ.get('PADIF_MCP_QA_UPLOAD') == '1':
                    for index in range(7):
                        upload_branch = 'file-'+uuid.uuid4().hex[:8]
                        await call('create_branch', dict(document_id=doc_id, name=upload_branch, fork_from_version_id=head, request_id=f'file-branch-{index}'))
                        task = await call('begin_markdown_upload', dict(document_id=doc_id, branch=upload_branch,
                            base_version_id=head, request_id=f'file-begin-{index}'))
                        if index == 0:
                            previous_refresh = storage.tokens.refresh_token
                            auth.context.token_expiry_time = time.time()-1
                            await session.list_tools()
                            assert storage.tokens.refresh_token != previous_refresh
                            assert (await call('get_markdown_upload_status', {'upload_id': task['upload_id']}))['state'] == 'awaiting_file'
                        (exchange / f'upload-{index}.json').write_text(json.dumps({'url': task['file_page_url'],
                            'upload_id': task['upload_id']}), encoding='utf-8')
                        deadline = time.monotonic()+90
                        marker = exchange / f'uploaded-{index}.json'
                        while not marker.exists():
                            assert time.monotonic() < deadline, 'Website file selection timed out'
                            await asyncio.sleep(.2)
                        expected = json.loads(marker.read_text(encoding='utf-8'))
                        received = await call('get_markdown_upload_status', {'upload_id': task['upload_id']})
                        assert received['state'] == 'uploaded'
                        verified = await call('validate_markdown_upload', {'upload_id': task['upload_id'], 'request_id': f'file-validate-{index}'})
                        assert verified['file_sha256'] == expected['file_sha256']
                        assert verified['content_sha256'] == expected['content_sha256']
                        if index == 0:
                            await call('compare_versions', verified['diff_ref']['arguments'])
                        committed = await call('commit_markdown_upload', dict(upload_id=task['upload_id'], commit_message='Website file QA',
                            version_kind='patch', request_id=f'file-commit-{index}'))
                        repeated = await call('commit_markdown_upload', dict(upload_id=task['upload_id'], commit_message='Website file QA',
                            version_kind='patch', request_id=f'file-retry-{index}'))
                        assert committed == repeated
                        digest = hashlib.sha256()
                        read_args = {'source_kind': 'version_markdown', 'source_id': committed['version']['id']}
                        while True:
                            part = await call('read_content_chunk', read_args)
                            digest.update(part['content'].encode('utf-8'))
                            if not part['next_cursor']:
                                break
                            read_args['cursor'] = part['next_cursor']
                        assert digest.hexdigest() == expected['content_sha256']
                    assert (await call('get_workspace', {'document_id': doc_id, 'include_content': False}))['current_version']['id'] == head
                old_refresh = storage.tokens.refresh_token
                auth.context.token_expiry_time = time.time() - 1
                await session.list_tools()
                assert storage.tokens.refresh_token != old_refresh
                # Browser now checks the visible connection and revokes it.
                (exchange / 'ready-to-revoke.json').write_text(json.dumps({'document_id': doc_id, 'branch': branch_name}), encoding='utf-8')
                deadline = time.monotonic() + 60
                while not (exchange / 'revoked.json').exists():
                    assert time.monotonic() < deadline, 'Browser revocation timed out'
                    await asyncio.sleep(.2)
                async with httpx.AsyncClient(trust_env=False) as verify:
                    denied = await verify.post(base + '/padif/mcp/', headers={'Authorization': 'Bearer ' + storage.tokens.access_token}, json={'jsonrpc': '2.0', 'id': 9, 'method': 'tools/list'})
                    assert denied.status_code == 401
                    denied_refresh = await verify.post(base + '/accounts/agent/oauth/token/', data={'client_id': storage.client_info.client_id, 'grant_type': 'refresh_token', 'refresh_token': storage.tokens.refresh_token, 'resource': base + '/padif/mcp/'})
                    assert denied_refresh.status_code == 400
                print('Official MCP SDK: OAuth/PKCE, 19 tools, bounded reads/diffs/replies, patches, optional seven website-file staging workflow, hash roundtrips, refresh and revocation passed; main unchanged.')


if __name__ == '__main__':
    asyncio.run(main())
