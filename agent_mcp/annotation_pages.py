"""Bounded annotation previews and connection-bound snapshot reply pages."""
from typing import Any

from django.core import signing
from django.http import Http404

from padif.models import Annotation, AnnotationReply, Version
from .long_documents import content_hash
from .models import Connection
from .tool_safety import MAX_TOOL_RESPONSE_BYTES, ToolFailure, response_bytes

CURSOR_SALT = 'padif-mcp-reply-page-v1'
CURSOR_MAX_AGE_SECONDS = 3600
MAX_INLINE_BYTES = 1024


def _text(target: dict, field: str, value: str, kind: str, source_id: int, *, refs: bool, force: bool = False) -> None:
    if refs and (force or len(value.encode('utf-8')) > MAX_INLINE_BYTES):
        target[field] = ''
        target[field+'_complete'] = False
        target[field+'_ref'] = {'source_kind': kind, 'source_id': source_id,
            'content_sha256': content_hash(value), 'normalization': 'utf8-no-bom-lf'}
    else:
        target[field] = value
        if refs:
            target[field+'_complete'] = True


def _reply(reply: AnnotationReply, *, refs: bool, force: bool = False) -> dict:
    item = {'id': reply.pk, 'author': reply.author.username, 'created_at': reply.created_at.isoformat()}
    _text(item, 'body', reply.body, 'reply_body', reply.pk, refs=refs, force=force)
    return item


def _cursor(connection: Connection, annotation: Annotation, upper: int, last: int) -> str:
    return signing.dumps({'connection': connection.pk, 'annotation': annotation.pk,
        'version': annotation.version_id, 'upper': upper, 'last': last}, salt=CURSOR_SALT)


def _reply_page(connection: Connection, annotation: Annotation, limit: int, *, cursor: str | None = None,
                refs: bool = True, force: bool = False) -> dict:
    replies = annotation.replies.select_related('author').order_by('pk')
    upper, last = replies.order_by('-pk').values_list('pk', flat=True).first() or 0, 0
    if cursor:
        try:
            data = signing.loads(cursor, salt=CURSOR_SALT, max_age=CURSOR_MAX_AGE_SECONDS)
        except signing.BadSignature as error:
            raise ToolFailure('INVALID_CURSOR') from error
        if (not isinstance(data, dict) or data.get('connection') != connection.pk
                or data.get('annotation') != annotation.pk or data.get('version') != annotation.version_id
                or type(data.get('upper')) is not int or type(data.get('last')) is not int
                or not 0 <= data['last'] <= data['upper']):
            raise ToolFailure('INVALID_CURSOR')
        upper, last = data['upper'], data['last']
    snapshot = replies.filter(pk__lte=upper)
    rows = list(snapshot.filter(pk__gt=last)[:limit+1])
    visible = rows[:limit]
    return {'items': [_reply(row, refs=refs, force=force) for row in visible], 'total': snapshot.count(),
        'next_reply_cursor': _cursor(connection, annotation, upper, visible[-1].pk) if len(rows) > limit else None,
        'replies_complete': last == 0 and len(rows) <= limit, 'snapshot_max_reply_id': upper}


def _annotation(connection: Connection, note: Annotation, values: dict, *, refs: bool, force: bool = False) -> dict:
    item = {'id': note.pk, 'version_id': note.version_id, 'kind': note.kind,
        'start_line': note.start_line, 'end_line': note.end_line, 'status': note.status,
        'author': note.author.username, 'created_at': note.created_at.isoformat(),
        'resolved_by': note.resolved_by.username if note.resolved_by else None,
        'resolved_at': note.resolved_at.isoformat() if note.resolved_at else None}
    _text(item, 'body', note.body, 'annotation_body', note.pk, refs=refs, force=force)
    _text(item, 'resolution_note', note.resolution_note, 'resolution_note', note.pk, refs=refs, force=force)
    item['selected_text'] = note.selected_text
    if refs and (force or len(note.selected_text.encode('utf-8')) > MAX_INLINE_BYTES):
        item.update(selected_text='', selected_text_complete=False,
            selected_text_ref={'source_kind': 'version_markdown', 'source_id': note.version_id,
                               'start_line': note.start_line, 'end_line': note.end_line})
    page = _reply_page(connection, note, values.get('reply_limit', 3) if refs else 100, refs=refs, force=force)
    if not refs and page['next_reply_cursor']:
        raise ToolFailure('OUTPUT_TOO_LARGE')
    item['replies'] = page['items']
    if refs:
        item.update(replies_total=page['total'], replies_complete=page['replies_complete'],
            next_reply_cursor=page['next_reply_cursor'], snapshot_max_reply_id=page['snapshot_max_reply_id'])
    return item


def list_annotations(connection: Connection, values: dict, response_id: Any = None) -> dict:
    if not Version.objects.filter(pk=values['version_id']).exists():
        raise Http404
    refs = values.get('paginate_replies', False) or any(key in values for key in ('reply_limit', 'reply_annotation_id', 'reply_cursor'))
    if 'reply_cursor' in values and 'reply_annotation_id' not in values:
        raise ToolFailure('INVALID_ARGUMENTS')
    if 'reply_annotation_id' in values:
        note = Annotation.objects.filter(pk=values['reply_annotation_id'], version_id=values['version_id']).first()
        if note is None:
            raise Http404
        if any(key in values for key in ('offset', 'status', 'kind')):
            raise ToolFailure('INVALID_ARGUMENTS')
        limit = values.get('reply_limit', values.get('limit', 20))
        # Requery with the same cursor when shrinking; never skip undisplayed replies.
        while True:
            result = _reply_page(connection, note, limit, cursor=values.get('reply_cursor'))
            result.update(reply_annotation_id=note.pk, version_id=note.version_id)
            if len(response_bytes(result, response_id)) <= MAX_TOOL_RESPONSE_BYTES:
                return result
            if limit == 1:
                result = _reply_page(connection, note, 1, cursor=values.get('reply_cursor'), force=True)
                result.update(reply_annotation_id=note.pk, version_id=note.version_id)
                return result
            limit = max(1, limit//2)
    query = Annotation.objects.filter(version_id=values['version_id']).select_related('author', 'resolved_by').order_by('pk')
    for field in ('status', 'kind'):
        if field in values:
            query = query.filter(**{field: values[field]})
    offset, limit = values.get('offset', 0), values.get('limit', 20)
    total = query.count()
    result = {'items': [], 'total': total, 'next_offset': None}
    for note in query[offset:offset+limit]:
        item = _annotation(connection, note, values, refs=refs)
        if refs and len(response_bytes({'item': item}, response_id)) > MAX_TOOL_RESPONSE_BYTES//2:
            item = _annotation(connection, note, {**values, 'reply_limit': 1}, refs=True, force=True)
        result['items'].append(item)
        result['next_offset'] = offset+len(result['items']) if offset+len(result['items']) < total else None
        if len(response_bytes(result, response_id)) > MAX_TOOL_RESPONSE_BYTES:
            if not refs or len(result['items']) == 1:
                raise ToolFailure('OUTPUT_TOO_LARGE')
            result['items'].pop()
            result['next_offset'] = offset+len(result['items'])
            break
    return result
