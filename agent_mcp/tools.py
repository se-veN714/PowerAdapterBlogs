"""Named writing operations. Existing Agent actions own the write semantics.

The internal adapter calls only the allowlisted, unwrapped API action after MCP
has authenticated the user and checked its scope; it never forwards an OAuth
token to the legacy device-token API or bypasses business validation.
"""
import hashlib
import inspect
import json
from urllib.parse import urlencode

from django.db import transaction
from django.http import Http404, HttpRequest, QueryDict
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from jsonschema import Draft202012Validator

from padif import api
from padif.models import Annotation, Branch, Document, Version
from padif.permissions import visible_documents, require_document, action_document_id
from .access import can_use_agent
from .config import origin
from .models import Connection, WriteReceipt
from .oauth import audit

ID = {'type': 'integer', 'minimum': 1}
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 10000}
PAGE = {'type': 'integer', 'minimum': 1, 'maximum': 100}


def tool(name, description, scope, properties, required=()):
    write = scope != 'padif:read'
    properties = dict(properties)
    if write:
        properties['request_id'] = {'type': 'string', 'minLength': 1, 'maxLength': 128, 'description': 'Unique per logical write; retain on network retry. New inputs require a new ID.'}
        required = (*required, 'request_id')
    return {'name': name, 'description': description, 'scope': scope,
            'inputSchema': {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False},
            'annotations': {'readOnlyHint': not write, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}}


TOOLS = [
    tool('list_documents', 'List documents explicitly shared with this user and enabled for AI+, filtered by title.', 'padif:read', {'query': {'type': 'string', 'maxLength': 200}, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': PAGE}),
    tool('get_workspace', 'Read branch head, complete current Markdown and bounded summaries. Use get_version for source lines; list_annotations for more comments.', 'padif:read', {'document_id': ID, 'branch': {'type': 'string', 'maxLength': 64}}, ['document_id']),
    tool('get_version', 'Read an immutable version, optionally a source-line range. Lines are 1-based Markdown source lines, including blank lines; wrapping adds no lines.', 'padif:read', {'version_id': ID, 'start_line': ID, 'end_line': ID}, ['version_id']),
    tool('compare_versions', 'Compare two versions of the same document; returns sentence changes, Markdown source line locations and statistics.', 'padif:read', {'document_id': ID, 'from_version': ID, 'to_version': ID}, ['document_id', 'from_version', 'to_version']),
    tool('list_annotations', 'List version annotations, their resolution notes and reply threads, filtered by status or kind.', 'padif:read', {'version_id': ID, 'status': {'enum': ['open', 'resolved', 'rejected']}, 'kind': {'enum': ['suggestion', 'explanation', 'question']}, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': PAGE}, ['version_id']),
    tool('create_branch', 'Create a writing branch from an existing version. Does not publish or change main.', 'padif:version', {'document_id': ID, 'name': {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9-]{0,63}$'}, 'fork_from_version_id': ID, 'description': {'type': 'string', 'maxLength': 1000}}, ['document_id', 'name', 'fork_from_version_id']),
    tool('commit_version', 'Append a full Markdown snapshot to an explicit non-main writing branch. Always supply its current effective head as base_version_id; on STALE_BASE_VERSION reread and revise. Updating main requires website confirmation.', 'padif:version', {'document_id': ID, 'branch': {'type': 'string', 'minLength': 1, 'maxLength': 64}, 'base_version_id': ID, 'content': {'type': 'string', 'minLength': 1, 'maxLength': 2097152}, 'commit_message': {'type': 'string', 'minLength': 1, 'maxLength': 300}, 'version_kind': {'enum': ['patch', 'minor', 'major']}}, ['document_id', 'branch', 'base_version_id', 'content', 'commit_message', 'version_kind']),
    tool('add_annotation', 'Add suggestion, explanation or question anchored to Markdown source lines of an immutable version. Blank lines count.', 'padif:annotate', {'version_id': ID, 'kind': {'enum': ['suggestion', 'explanation', 'question']}, 'body': TEXT, 'start_line': ID, 'end_line': ID, 'selected_text': {'type': 'string', 'maxLength': 10000}}, ['version_id', 'kind', 'body', 'start_line', 'end_line']),
    tool('reply_annotation', 'Append an authored, timestamped reply to an existing annotation.', 'padif:annotate', {'annotation_id': ID, 'body': TEXT}, ['annotation_id', 'body']),
    tool('resolve_annotation', 'Mark an annotation resolved or rejected. A nonblank explanation is mandatory.', 'padif:annotate', {'annotation_id': ID, 'status': {'enum': ['resolved', 'rejected']}, 'resolution_note': TEXT}, ['annotation_id', 'status', 'resolution_note']),
]
BY_NAME = {item['name']: item for item in TOOLS}


def _action(view, user, *, method='POST', payload=None, query=None, scopes=None, **kwargs):
    request = HttpRequest()
    request.method = method
    request.path = '/'
    request.GET = QueryDict('', mutable=True)
    request.GET.update(query or {})
    request._body = json.dumps(payload or {}).encode('utf-8')
    request.META['CONTENT_TYPE'] = 'application/json'
    request.agent_user = user
    request.agent_scopes = scopes or []
    response = inspect.unwrap(view)(request, **kwargs)
    result = json.loads(response.content)
    if response.status_code >= 400:
        result['http_status'] = response.status_code
    return result


def _page(queryset, values, serializer):
    offset, limit = values.get('offset', 0), values.get('limit', 20)
    total = queryset.count()
    return {'items': [serializer(item) for item in queryset[offset:offset + limit]], 'total': total,
            'next_offset': offset + limit if offset + limit < total else None}


def _execute(name, values, user, scopes=None):
    values = dict(values)
    values.pop('request_id', None)
    if name == 'list_documents':
        docs = visible_documents(user, agent=True).select_related('current_version').filter(title__icontains=values.get('query', '')).order_by('-pk')
        return _page(docs, values, lambda doc: {'id': doc.pk, 'title': doc.title,
                     'current_version_id': doc.current_version_id, 'url': origin() + f'/padif/documents/{doc.pk}/'})
    if name == 'get_workspace':
        result = _action(api.workspace, user, scopes=scopes, method='GET', query={'branch': values.get('branch', 'main')}, document_id=values['document_id'])
        if 'versions' in result:
            result['versions_truncated'] = len(result['versions']) > 50
            result['versions'] = result['versions'][-50:]
            result['annotations_truncated'] = len(result['annotations']) > 50
            result['annotations'] = result['annotations'][:50]
            result['url'] = origin() + f'/padif/documents/{values["document_id"]}/?' + urlencode({'branch': values.get('branch', 'main')})
        return result
    if name == 'get_version':
        version = Version.objects.select_related('branch', 'created_by').filter(pk=values['version_id']).first()
        if version is None:
            return {'error': 'VERSION_NOT_FOUND'}
        lines = version.content.replace('\r\n', '\n').split('\n')
        start, end = values.get('start_line', 1), values.get('end_line', len(lines))
        if end < start or start > len(lines) or end > len(lines):
            return {'error': 'INVALID_SOURCE_RANGE'}
        return {**api._version_payload(version), 'document_id': version.document_id,
                'start_line': start, 'end_line': end, 'total_lines': len(lines),
                'content': '\n'.join(lines[start - 1:end])}
    if name == 'compare_versions':
        return _action(api.diff, user, method='GET', query=values, document_id=values['document_id'])
    if name == 'list_annotations':
        if not Version.objects.filter(pk=values['version_id']).exists():
            return {'error': 'VERSION_NOT_FOUND'}
        annotations = Annotation.objects.filter(version_id=values['version_id']).select_related('author', 'resolved_by').order_by('pk')
        for field in ('status', 'kind'):
            if field in values:
                annotations = annotations.filter(**{field: values[field]})
        return _page(annotations, values, api._annotation_payload)
    if name == 'add_annotation':
        version = Version.objects.filter(pk=values['version_id']).first()
        if version is None:
            return {'error': 'VERSION_NOT_FOUND'}
        lines = version.content.replace('\r\n', '\n').split('\n')
        if values['end_line'] < values['start_line'] or values['end_line'] > len(lines):
            return {'error': 'INVALID_SOURCE_RANGE'}
        if values.get('selected_text') and values['selected_text'] not in '\n'.join(lines[values['start_line'] - 1:values['end_line']]):
            return {'error': 'SELECTED_TEXT_MISMATCH'}
    if name == 'commit_version' and Branch.objects.filter(document_id=values['document_id'], name=values['branch'], is_default=True).exists():
        return {'error': 'MAIN_REQUIRES_WEB_CONFIRMATION'}
    actions = {
        'create_branch': (api.create_branch, 'document_id', 'POST'),
        'commit_version': (api.commit_version, 'document_id', 'POST'),
        'add_annotation': (api.create_annotation, 'version_id', 'POST'),
        'reply_annotation': (api.create_reply, 'annotation_id', 'POST'),
        'resolve_annotation': (api.update_annotation, 'annotation_id', 'PATCH'),
    }
    view, id_field, method = actions[name]
    object_id = values.pop(id_field)
    if name == 'commit_version' and len(values['content'].encode('utf-8')) > 2 * 1024 * 1024:
        return {'error': 'CONTENT_TOO_LARGE'}
    result = _action(view, user, method=method, payload=values, **{id_field: object_id})
    if 'error' not in result:
        document_id = object_id if id_field == 'document_id' else None
        if id_field == 'version_id':
            document_id = Version.objects.get(pk=object_id).document_id
        elif id_field == 'annotation_id':
            document_id = Annotation.objects.get(pk=object_id).version.document_id
        result['url'] = origin() + f'/padif/documents/{document_id}/'
        branch_name = result.get('branch', {}).get('name')
        if not branch_name and id_field == 'version_id':
            branch_name = Version.objects.get(pk=object_id).branch.name
        elif not branch_name and id_field == 'annotation_id':
            branch_name = Annotation.objects.get(pk=object_id).version.branch.name
        if branch_name:
            result['url'] += '?' + urlencode({'branch': branch_name})
    return result


def _check_document(connection, name, values, *, write=False):
    if name == 'list_documents':
        return
    document_id = action_document_id(values)
    query = Document.objects.filter(pk=document_id)
    if write:
        query = query.select_for_update()
    document = query.first()
    if document is None:
        raise Http404
    require_document(connection.user, document, write=write, agent=True, operation=BY_NAME[name]['scope'])


def call_tool(connection, name, values):
    definition = BY_NAME.get(name)
    if definition is None:
        return {'error': 'UNKNOWN_TOOL'}
    if definition['scope'] not in connection.scopes:
        return {'error': 'INSUFFICIENT_SCOPE', 'required_scope': definition['scope']}
    errors = list(Draft202012Validator(definition['inputSchema']).iter_errors(values))
    if errors:
        # Do not echo manuscript bodies in validation errors/logs.
        return {'error': 'INVALID_ARGUMENTS', 'field': '.'.join(map(str, errors[0].path))}
    try:
        if definition['scope'] == 'padif:read':
            _check_document(connection, name, values)
            return _execute(name, values, connection.user, connection.scopes)
        digest = hashlib.sha256(json.dumps([name, values], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with transaction.atomic():
            locked = Connection.objects.select_for_update().get(pk=connection.pk)
            locked.user.refresh_from_db()
            if locked.revoked_at is not None or locked.expires_at <= timezone.now() or not can_use_agent(locked.user):
                return {'error': 'INVALID_TOKEN'}
            _check_document(connection, name, values, write=True)
            receipt = WriteReceipt.objects.filter(connection=connection, request_id=values['request_id']).first()
            if receipt:
                return receipt.result if receipt.input_digest == digest else {'error': 'REQUEST_ID_CONFLICT'}
            result = _execute(name, values, connection.user, connection.scopes)
            if 'error' not in result:
                WriteReceipt.objects.create(connection=connection, request_id=values['request_id'], input_digest=digest, result=result)
                audit('agent.mcp.' + name, connection)
            return result
    except Http404:
        return {'error': 'NOT_FOUND'}
    except PermissionDenied:
        return {'error': 'DOCUMENT_PERMISSION_DENIED'}
