"""Bounded MCP manuscript reads and exact source-line patches, never file paths."""
import re
from typing import Any

from django.core import signing
from django.http import Http404

from padif import api
from padif.models import Annotation, AnnotationReply, Document, Version
from padif.permissions import agent_permission_payload
from padif.services import MAX_UPLOAD_BYTES, commit_document_version, effective_head, resolve_branch
from .models import Connection
from .tool_safety import MAX_CONTENT_CHUNK_BYTES, MAX_TOOL_RESPONSE_BYTES, ToolFailure, response_bytes, canonical_content, content_hash
from . import uploads

CURSOR_SALT = 'padif-mcp-source-chunk-v1'
CURSOR_MAX_AGE_SECONDS = 3600
SOURCE_MODELS = {
    'version_markdown': (Version, 'content', 'document_id'),
    'annotation_body': (Annotation, 'body', 'version__document_id'),
    'resolution_note': (Annotation, 'resolution_note', 'version__document_id'),
    'reply_body': (AnnotationReply, 'body', 'annotation__version__document_id'),
}


def source_document_id(kind: str, source_id: int) -> int | None:
    model, _, lookup = SOURCE_MODELS[kind]
    return model.objects.filter(pk=source_id).values_list(lookup, flat=True).first()


def version_metadata(version: Version) -> dict:
    content = canonical_content(version.content)
    return {**api._version_payload(version), 'content_sha256': content_hash(content),
            'content_bytes': len(content.encode('utf-8')), 'total_lines': content.count('\n') + 1,
            'normalization': 'utf8-no-bom-lf', 'content_is_untrusted': True}


def _branch_summary(branch: Any) -> dict:
    head = branch.versions.order_by('-pk').values('id', 'semantic_version').first()
    if head is None and branch.forked_from_id:
        head = Version.objects.filter(pk=branch.forked_from_id).values('id', 'semantic_version').first()
    return {'id': branch.pk, 'name': branch.name, 'is_default': branch.is_default,
            'forked_from_version_id': branch.forked_from_id, 'head_version_id': head['id'] if head else None,
            'head_semantic_version': head['semantic_version'] if head else None,
            'archived_at': branch.archived_at.isoformat() if branch.archived_at else None}


def workspace_summary(document: Document, user: Any, scopes: list[str], branch_name: str | None) -> dict:
    branch = resolve_branch(document, name=branch_name)
    current = effective_head(branch)
    versions = list(document.versions.select_related('created_by', 'branch').defer('content').order_by('-pk')[:51])
    annotations = list(current.annotations.values('id', 'kind', 'status', 'start_line', 'end_line')[:51]) if current else []
    branches = list(document.branches.all()[:101])
    return {'document': {'id': document.pk, 'title': document.title, 'source_name': document.source_name},
            'permissions': agent_permission_payload(user, document, scopes),
            'current_version': version_metadata(current) if current else None,
            'content_included': False, 'versions': [api._version_payload(item) for item in reversed(versions[:50])],
            'versions_truncated': len(versions) > 50, 'annotations': annotations[:50],
            'annotations_summary_only': True, 'annotations_truncated': len(annotations) > 50,
            'selected_branch': _branch_summary(branch),
            'branches': [_branch_summary(item) for item in branches[:100]], 'branches_truncated': len(branches) > 100}


def _outline_headings(content: str) -> list[dict]:
    """Source positions for ATX/setext headings outside fenced code blocks."""
    lines = content.split('\n')
    headings = []
    fence_char, fence_length = '', 0
    for index, line in enumerate(lines):
        fence = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            marker, suffix = fence.groups()
            if not fence_char:
                fence_char, fence_length = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length and not suffix.strip():
                fence_char = ''
            continue
        if fence_char:
            continue
        heading = re.match(r'^ {0,3}(#{1,6})(?:[ \t]+(.*?)|[ \t]*)$', line)
        if heading:
            level, title = len(heading[1]), re.sub(r'[ \t]+#+[ \t]*$', '', heading[2] or '').strip()
            source_line = index + 1
        elif index and re.fullmatch(r' {0,3}(?:=+|-+)[ \t]*', line) and lines[index-1].strip():
            previous = lines[index-1]
            if re.match(r'^ {0,3}(?:`{3,}|~{3,}|#{1,6}[ \t])', previous) or previous.startswith('    '):
                continue
            level, title, source_line = (1 if line.strip().startswith('=') else 2), previous.strip(), index
        else:
            continue
        headings.append({'level': level, 'title': title[:200], 'title_truncated': len(title) > 200, 'line': source_line})
        if len(headings) > 10000:
            raise ToolFailure('CONTENT_TOO_COMPLEX')
    return headings


def document_outline(document: Document, values: dict) -> dict:
    if 'version_id' in values:
        if 'branch' in values:
            raise ToolFailure('INVALID_ARGUMENTS')
        version = document.versions.select_related('branch', 'created_by').filter(pk=values['version_id']).first()
    else:
        version = effective_head(resolve_branch(document, name=values.get('branch')))
    if version is None:
        raise Http404
    headings = _outline_headings(canonical_content(version.content))
    offset, limit = values.get('offset', 0), values.get('limit', 20)
    return {'document_id': document.pk, 'version': version_metadata(version), 'items': headings[offset:offset+limit],
            'total': len(headings), 'next_offset': offset+limit if offset+limit < len(headings) else None}


def read_content_chunk(connection: Connection, values: dict, response_id: Any = None) -> dict:
    kind, source_id = values['source_kind'], values['source_id']
    if kind == 'upload_markdown':
        original = uploads.read_staged(connection, source_id)
    else:
        model, field, _ = SOURCE_MODELS[kind]
        original = model.objects.filter(pk=source_id).values_list(field, flat=True).first()
    if original is None:
        raise Http404
    content = canonical_content(original)
    digest = content_hash(content)
    encoded = content.encode('utf-8')
    start = 0
    binding = {'connection': connection.pk, 'kind': kind, 'source': source_id, 'sha256': digest}
    if values.get('cursor'):
        try:
            cursor = signing.loads(values['cursor'], salt=CURSOR_SALT, max_age=CURSOR_MAX_AGE_SECONDS)
        except signing.BadSignature as error:
            raise ToolFailure('INVALID_CURSOR') from error
        if not isinstance(cursor, dict) or any(cursor.get(key) != value for key, value in binding.items() if key != 'sha256'):
            raise ToolFailure('INVALID_CURSOR')
        if cursor.get('sha256') != digest:
            raise ToolFailure('STALE_CONTENT')
        start = cursor.get('offset')
        if type(start) is not int or not 0 <= start <= len(encoded):
            raise ToolFailure('INVALID_CURSOR')
        if start < len(encoded) and encoded[start] & 0xC0 == 0x80:
            raise ToolFailure('INVALID_CURSOR')
    end = min(len(encoded), start + values.get('max_bytes', MAX_CONTENT_CHUNK_BYTES))
    # Both UTF-8 boundaries and actual JSON-RPC size matter (control chars expand).
    while True:
        piece = encoded[start:end].decode('utf-8', errors='ignore')
        end = start + len(piece.encode('utf-8'))
        cursor = signing.dumps({**binding, 'offset': end}, salt=CURSOR_SALT) if end < len(encoded) else None
        prefix = encoded[:start].decode('utf-8')
        result = {'source_kind': kind, 'source_id': source_id, 'content_sha256': digest, 'content': piece,
                  'content_is_untrusted': True, 'normalization': 'utf8-no-bom-lf', 'total_bytes': len(encoded),
                  'start_byte': start, 'end_byte_exclusive': end, 'next_cursor': cursor,
                  'start_line': prefix.count('\n')+1,
                  'end_line': prefix.count('\n')+piece.count('\n')+1-int(piece.endswith('\n')),
                  'starts_mid_line': bool(prefix and not prefix.endswith('\n')),
                  'ends_mid_line': bool(end < len(encoded) and not piece.endswith('\n'))}
        if len(response_bytes(result, response_id)) <= MAX_TOOL_RESPONSE_BYTES:
            return result
        if end <= start:
            raise ToolFailure('OUTPUT_TOO_LARGE')
        end = start + max(1, (end-start)//2)


def apply_version_patch(document: Document, user: Any, values: dict) -> dict:
    branch = resolve_branch(document, name=values['branch'])
    if branch.is_default:
        raise ToolFailure('MAIN_REQUIRES_WEB_CONFIRMATION')
    base = effective_head(branch)
    if base is None or base.pk != values['base_version_id']:
        raise ToolFailure('STALE_BASE_VERSION')
    content = canonical_content(base.content)
    if content_hash(content) != values['base_content_sha256']:
        raise ToolFailure('PATCH_BASE_MISMATCH')
    lines = content.split('\n')
    edits = sorted(values['edits'], key=lambda edit: (edit['start_line'], edit['end_line_exclusive']))
    previous_start, previous_end = 0, 0
    replacement_bytes = 0
    for edit in edits:
        if any('\n' in line or '\r' in line for line in [*edit['expected_lines'], *edit['replacement_lines']]):
            raise ToolFailure('INVALID_ARGUMENTS')
        start, end = edit['start_line'], edit['end_line_exclusive']
        if not 1 <= start <= end <= len(lines)+1:
            raise ToolFailure('INVALID_SOURCE_RANGE')
        if start < previous_end or start == previous_start:
            raise ToolFailure('PATCH_OVERLAP')
        if lines[start-1:end-1] != edit['expected_lines']:
            raise ToolFailure('PATCH_SOURCE_MISMATCH')
        replacement_bytes += len('\n'.join(edit['replacement_lines']).encode('utf-8'))
        previous_start, previous_end = start, end
    if replacement_bytes > 32 * 1024:
        raise ToolFailure('CONTENT_TOO_LARGE')
    for edit in reversed(edits):
        lines[edit['start_line']-1:edit['end_line_exclusive']-1] = edit['replacement_lines']
    updated = '\n'.join(lines)
    if len(updated.encode('utf-8')) > MAX_UPLOAD_BYTES:
        raise ToolFailure('CONTENT_TOO_LARGE')
    committed = commit_document_version(document_id=document.pk, user=user, branch_id=branch.pk,
        base_version_id=base.pk, content=updated, commit_message=values['commit_message'], version_kind=values['version_kind'])
    return {'version': api._version_payload(committed.version), 'branch': api._branch_payload(branch),
            'base_version_id': base.pk, 'content_sha256': content_hash(updated), 'normalization': 'utf8-no-bom-lf'}
