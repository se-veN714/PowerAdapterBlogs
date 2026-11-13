"""Private, transactional Markdown staging. Bytes never enter public media."""
import base64
import binascii
import hashlib
import math
import re
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.urls import reverse
from django.utils import timezone

from accounts.agent_auth import _audit_agent_event
from padif import api
from padif.models import Document
from padif.permissions import require_document, document_role
from padif.services import commit_document_version, effective_head, resolve_branch
from .access import can_use_agent
from .config import origin
from .models import AgentQualification, Connection, MarkdownUpload, MarkdownUploadChunk, UploadCapacity
from .tool_safety import ToolFailure, canonical_content, content_hash

S = MarkdownUpload.State
ACTIVE = (S.AWAITING, S.RECEIVING, S.UPLOADED, S.VALIDATED)
UPLOAD_TOOLS = frozenset({'begin_markdown_upload', 'append_markdown_chunk', 'get_markdown_upload_status',
    'validate_markdown_upload', 'commit_markdown_upload', 'cancel_markdown_upload'})
CHUNK_BYTES = 16384
FILE_BYTES = 2*1024*1024


def audit_upload(task: MarkdownUpload, event: str) -> None:
    _audit_agent_event(event_type='agent.mcp.upload.'+event, actor=task.user,
        target_type='mcp_upload', target_id=str(task.pk), source='padif_mcp',
        change={'state': task.state, 'file_sha256': task.file_sha256, 'content_sha256': task.content_sha256,
                'failure_code': task.failure_code, 'document_id': task.document_id})


def basis(connection: Connection, document: Document) -> dict:
    return {'qualification': AgentQualification.objects.filter(user_id=connection.user_id, module_key='padif').values_list('revision', flat=True).first(),
            'grant': document.agent_grants.filter(user_id=connection.user_id).values_list('revision', flat=True).first(),
            'role': document_role(connection.user, document),
            'collaboration': document.collaborators.filter(user_id=connection.user_id).values_list('revision', flat=True).first()}


def terminal(task: MarkdownUpload, state: str, code: str = '') -> dict:
    task.state, task.failure_code, task.reserved_bytes = state, code, 0
    task.chunks.all().delete()
    task.purged_at = timezone.now()
    task.save(update_fields=['state', 'failure_code', 'reserved_bytes', 'purged_at'])
    audit_upload(task, state)
    return {'error': code or 'UPLOAD_'+state.upper(), 'upload_id': str(task.pk), 'state': state}


def status(task: MarkdownUpload) -> dict:
    count = math.ceil(task.file_size/CHUNK_BYTES) if task.file_size else 0
    received = list(task.chunks.order_by('index').values_list('index', flat=True))
    return {'upload_id': str(task.pk), 'state': task.state, 'document_id': task.document_id,
        'branch': task.branch.name, 'base_version_id': task.base_version_id,
        'file_name': task.file_name, 'file_size': task.file_size, 'file_sha256': task.file_sha256,
        'content_sha256': task.content_sha256, 'normalization': 'utf8-no-bom-lf',
        'expires_at': task.expires_at.isoformat(), 'chunk_bytes': CHUNK_BYTES,
        'total_chunks': count, 'received_indices': received,
        'missing_indices': [i for i in range(count) if i not in received] if task.state in (S.RECEIVING, S.UPLOADED) else [],
        'failure_code': task.failure_code, 'committed_version_id': task.committed_version_id,
        'file_page_url': origin()+reverse('agent_mcp:upload-file', args=[task.pk])}


def manifest_values(values: dict) -> tuple[str, int, str]:
    name, size, digest = values.get('file_name'), values.get('file_size'), values.get('file_sha256')
    if (not isinstance(name, str) or not 1 <= len(name) <= 120 or name != name.strip()
            or any(ord(c) < 32 or ord(c) == 127 or c in '/\\:' for c in name)
            or '..' in name or not name.lower().endswith(('.md', '.markdown'))):
        raise ToolFailure('INVALID_FILE_NAME')
    if type(size) is not int or not 1 <= size <= FILE_BYTES:
        raise ToolFailure('CONTENT_TOO_LARGE')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ToolFailure('INVALID_FILE_HASH')
    return name, size, digest


def rate(connection: Connection, action: str, limit: int) -> None:
    key = f'mcp-upload:{connection.pk}:{action}:{int(time.time())//60}'
    if not cache.add(key, 1, 65) and cache.incr(key) > limit:
        raise ToolFailure('RATE_LIMITED')


def create(connection: Connection, values: dict) -> dict:
    rate(connection, 'begin', 10)
    document = Document.objects.get(pk=values['document_id'])
    branch = resolve_branch(document, name=values['branch'])
    if branch.is_default:
        raise ToolFailure('MAIN_REQUIRES_WEB_CONFIRMATION')
    if branch.archived_at or effective_head(branch).pk != values['base_version_id']:
        raise ToolFailure('STALE_BASE_VERSION')
    supplied = any(key in values for key in ('file_name', 'file_size', 'file_sha256'))
    manifest = manifest_values(values) if supplied else None
    reserved = manifest[1] if manifest else FILE_BYTES
    UploadCapacity.objects.get_or_create(pk=1)
    UploadCapacity.objects.select_for_update().get(pk=1)
    active = MarkdownUpload.objects.filter(state__in=ACTIVE)
    personal = active.filter(user_id=connection.user_id, expires_at__gt=timezone.now())
    if personal.count() >= 3 or (personal.aggregate(size=Sum('reserved_bytes'))['size'] or 0)+reserved > 8*1024*1024:
        raise ToolFailure('UPLOAD_QUOTA_EXCEEDED')
    if (active.count() >= getattr(settings, 'MCP_UPLOAD_MAX_ACTIVE', 1024)
            or (active.aggregate(size=Sum('reserved_bytes'))['size'] or 0)+reserved > getattr(settings, 'MCP_UPLOAD_MAX_BYTES', 128*1024*1024)):
        raise ToolFailure('UPLOAD_CAPACITY_EXCEEDED')
    task = MarkdownUpload.objects.create(user_id=connection.user_id, connection=connection, document=document,
        branch=branch, base_version_id=values['base_version_id'], basis=basis(connection, document),
        expires_at=timezone.now()+timedelta(minutes=30), reserved_bytes=reserved)
    if manifest:
        bind_manifest(task, values)
    audit_upload(task, 'created')
    return status(task)


def bind_manifest(task: MarkdownUpload, values: dict) -> dict:
    manifest = manifest_values(values)
    if task.state != S.AWAITING:
        if manifest == (task.file_name, task.file_size, task.file_sha256):
            return status(task)
        raise ToolFailure('MANIFEST_CONFLICT')
    task.file_name, task.file_size, task.file_sha256 = manifest
    task.reserved_bytes, task.state = task.file_size, S.RECEIVING
    task.save(update_fields=['file_name', 'file_size', 'file_sha256', 'reserved_bytes', 'state'])
    audit_upload(task, 'manifest_bound')
    return status(task)


def guard(connection: Connection, task: MarkdownUpload) -> dict | None:
    if task.state not in ACTIVE:
        return None
    if task.expires_at <= timezone.now():
        return terminal(task, S.EXPIRED, 'UPLOAD_EXPIRED')
    if task.basis != basis(connection, task.document):
        return terminal(task, S.INVALIDATED, 'UPLOAD_AUTHORIZATION_CHANGED')
    if task.branch.is_default or task.branch.archived_at or effective_head(task.branch).pk != task.base_version_id:
        return terminal(task, S.INVALIDATED, 'STALE_BASE_VERSION')
    return None


def get_task(connection: Connection, upload_id: str) -> MarkdownUpload:
    task = MarkdownUpload.objects.select_for_update().filter(pk=upload_id, connection=connection,
        user_id=connection.user_id).select_related('document', 'branch').first()
    if task is None:
        raise Http404
    return task


def append(connection: Connection, task: MarkdownUpload, values: dict) -> dict:
    if task.state not in (S.RECEIVING, S.UPLOADED):
        raise ToolFailure('UPLOAD_STATE_CONFLICT')
    rate(connection, 'append', 60)
    encoded, index = values['data_base64'], values['chunk_index']
    if not isinstance(encoded, str) or len(encoded) > 4*math.ceil(CHUNK_BYTES/3):
        raise ToolFailure('CONTENT_TOO_LARGE')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ToolFailure('INVALID_CHUNK') from error
    total = math.ceil(task.file_size/CHUNK_BYTES)
    expected = CHUNK_BYTES if index < total-1 else task.file_size-CHUNK_BYTES*(total-1)
    if type(index) is not int or not 0 <= index < total or len(data) != expected or hashlib.sha256(data).hexdigest() != values['chunk_sha256']:
        raise ToolFailure('INVALID_CHUNK')
    existing = task.chunks.filter(index=index).first()
    if existing:
        if bytes(existing.data) != data or existing.sha256 != values['chunk_sha256']:
            raise ToolFailure('CHUNK_CONFLICT')
        return status(task)
    MarkdownUploadChunk.objects.create(upload=task, index=index, sha256=values['chunk_sha256'], data=data)
    if task.chunks.count() == total:
        task.state = S.UPLOADED
        task.save(update_fields=['state'])
    return status(task)


def raw_bytes(task: MarkdownUpload) -> bytes:
    return b''.join(bytes(chunk.data) for chunk in task.chunks.order_by('index'))


def validated_content(task: MarkdownUpload) -> str:
    data = raw_bytes(task)
    if len(data) != task.file_size or hashlib.sha256(data).hexdigest() != task.file_sha256:
        raise ToolFailure('FILE_INTEGRITY_FAILED')
    try:
        content = canonical_content(data.decode('utf-8'))
    except UnicodeDecodeError as error:
        raise ToolFailure('INVALID_MARKDOWN_ENCODING') from error
    if (not content.strip() or any(ord(c) < 32 and c not in '\r\n\t' or ord(c) == 127 for c in content)
            or data.startswith((b'PK\x03\x04', b'\x7fELF', b'%PDF-', b'\x89PNG', b'GIF87a', b'GIF89a', b'\xff\xd8\xff'))):
        raise ToolFailure('INVALID_MARKDOWN_CONTENT')
    return content


def execute(connection: Connection, name: str, values: dict) -> dict:
    if name == 'begin_markdown_upload':
        return create(connection, values)
    task = get_task(connection, values['upload_id'])
    rejected = guard(connection, task)
    if rejected:
        return rejected
    if name == 'get_markdown_upload_status':
        return status(task)
    if name == 'cancel_markdown_upload':
        if task.state == S.COMMITTED:
            raise ToolFailure('UPLOAD_ALREADY_COMMITTED')
        if task.state == S.CANCELLED:
            return status(task)
        if task.state not in ACTIVE:
            raise ToolFailure('UPLOAD_STATE_CONFLICT')
        terminal(task, S.CANCELLED)
        return status(task)
    if name == 'append_markdown_chunk':
        return append(connection, task, values)
    if name == 'validate_markdown_upload':
        if task.state not in (S.UPLOADED, S.VALIDATED):
            raise ToolFailure('UPLOAD_INCOMPLETE')
        try:
            content = validated_content(task)
        except ToolFailure as error:
            return terminal(task, S.INVALIDATED, error.code)
        task.state, task.content_sha256 = S.VALIDATED, content_hash(content)
        task.save(update_fields=['state', 'content_sha256'])
        audit_upload(task, 'validated')
        return {**status(task), 'summary': {'bytes': len(content.encode('utf-8')), 'source_lines': content.count('\n')+1},
            'diff_ref': {'tool': 'compare_versions', 'arguments': {'document_id': task.document_id,
                'from_version': task.base_version_id, 'to_upload_id': str(task.pk), 'offset': 0, 'limit': 20}}}
    if name == 'commit_markdown_upload':
        if task.state == S.COMMITTED:
            return task.commit_result
        if task.state != S.VALIDATED:
            raise ToolFailure('UPLOAD_NOT_VALIDATED')
        try:
            content = validated_content(task)
        except ToolFailure as error:
            return terminal(task, S.INVALIDATED, error.code)
        if content_hash(content) != task.content_sha256:
            return terminal(task, S.INVALIDATED, 'FILE_INTEGRITY_FAILED')
        committed = commit_document_version(document_id=task.document_id, user=connection.user, branch_id=task.branch_id,
            base_version_id=task.base_version_id, content=content, commit_message=values['commit_message'], version_kind=values['version_kind'])
        task.committed_version = committed.version
        task.state, task.reserved_bytes = S.COMMITTED, 0
        task.commit_result = {'upload_id': str(task.pk), 'version': api._version_payload(committed.version),
            'file_sha256': task.file_sha256, 'content_sha256': task.content_sha256, 'normalization': 'utf8-no-bom-lf'}
        task.chunks.all().delete()
        task.purged_at = timezone.now()
        task.save(update_fields=['committed_version', 'state', 'reserved_bytes', 'commit_result', 'purged_at'])
        audit_upload(task, 'committed')
        return task.commit_result
    raise ToolFailure('UNKNOWN_TOOL')


@transaction.atomic
def cleanup_task(upload_id: str) -> bool:
    record = MarkdownUpload.objects.get(pk=upload_id)
    connection = Connection.objects.select_for_update().get(pk=record.connection_id)
    document = Document.objects.select_for_update().get(pk=record.document_id)
    task = get_task(connection, str(record.pk))
    if task.state not in ACTIVE:
        return False
    if connection.revoked_at or connection.expires_at <= timezone.now() or not can_use_agent(connection.user) or 'padif:version' not in connection.scopes:
        terminal(task, S.INVALIDATED, 'UPLOAD_AUTHORIZATION_CHANGED')
        return True
    try:
        require_document(connection.user, document, write=True, agent=True, operation='padif:version')
    except (PermissionDenied, Http404):
        terminal(task, S.INVALIDATED, 'UPLOAD_AUTHORIZATION_CHANGED')
        return True
    return guard(connection, task) is not None


def read_staged(connection: Connection, upload_id: str) -> str:
    """Preserve an invalidation transaction before reporting a rejected read."""
    rejected = None
    content = ''
    with transaction.atomic():
        fresh = Connection.objects.select_for_update().get(pk=connection.pk)
        if fresh.revoked_at or fresh.expires_at <= timezone.now() or not can_use_agent(fresh.user) or 'padif:version' not in fresh.scopes or 'padif:version' not in connection.scopes:
            raise ToolFailure('INVALID_TOKEN')
        task = MarkdownUpload.objects.filter(pk=upload_id, connection=fresh, user_id=fresh.user_id).first()
        if task is None:
            raise Http404
        document = Document.objects.select_for_update().get(pk=task.document_id)
        require_document(fresh.user, document, write=True, agent=True, operation='padif:version')
        task = get_task(fresh, upload_id)
        rejected = guard(fresh, task)
        if rejected is None:
            if task.state == S.COMMITTED:
                content = canonical_content(task.committed_version.content)
            elif task.state == S.VALIDATED:
                try:
                    content = validated_content(task)
                except ToolFailure as error:
                    rejected = terminal(task, S.INVALIDATED, error.code)
            else:
                raise ToolFailure('UPLOAD_NOT_VALIDATED')
    if rejected:
        raise ToolFailure(rejected['error'])
    return content
