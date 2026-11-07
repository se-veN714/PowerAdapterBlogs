"""Real official-SDK OAuth + Streamable HTTP acceptance; local QA only.

Run through browser_oauth.cjs: tokens stay in memory; the browser supplies the
authorization callback via a per-run ignored directory. Only the named local
fixture document is modified, always on a new writing branch.
"""
import asyncio
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
                assert len(listed.tools) == 10
                assert not any('publish' in item.name for item in listed.tools)

                async def call(name, args):
                    result = await session.call_tool(name, args)
                    assert not result.isError, result.content
                    return result.structuredContent

                docs = await call('list_documents', {'query': 'MCP 本地验收'})
                assert docs['total'] == 1
                doc_id = docs['items'][0]['id']
                workspace = await call('get_workspace', {'document_id': doc_id})
                head = workspace['current_version']['id']
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
                await call('resolve_annotation', dict(annotation_id=annotation_id, status='resolved', resolution_note='Verified locally.', request_id='resolve'))
                assert (await call('list_annotations', dict(version_id=version_id, status='resolved')))['total'] == 1
                await call('compare_versions', dict(document_id=doc_id, from_version=head, to_version=version_id))
                assert (await call('get_workspace', {'document_id': doc_id}))['current_version']['id'] == head
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
                print('Official MCP SDK: OAuth discovery/PKCE, 10 tools, branch writes, idempotency, comments, source lines, token refresh and browser revocation passed; main unchanged.')


if __name__ == '__main__':
    asyncio.run(main())
