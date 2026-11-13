"""Session-authenticated personal drafts, outside the version/publication APIs."""
import json
import uuid

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache

from .models import Document, EditorDraft
from .permissions import document_role
from .views import padif_access_required

MAX_BODY_BYTES = 2 * 1024 * 1024


def payload(draft):
    return {'content': draft.content, 'commit_message': draft.commit_message,
            'version_kind': draft.version_kind, 'revision': str(draft.revision),
            'base_version_id': draft.base_version_id, 'updated_at': draft.updated_at.isoformat()}


@never_cache
@padif_access_required
def editor_draft(request, document_id, branch_id, version_id):
    if request.method not in {'GET', 'POST'}:
        return JsonResponse({'error': 'METHOD_NOT_ALLOWED'}, status=405)
    document = get_object_or_404(Document, pk=document_id)
    branch = get_object_or_404(document.branches, pk=branch_id)
    base = get_object_or_404(document.versions, pk=version_id)
    if base.branch_id != branch.pk and base.pk != branch.forked_from_id:
        return JsonResponse({'error': 'INVALID_BASE'}, status=404)
    query = EditorDraft.objects.filter(user=request.user, document=document, branch=branch, base_version=base)
    if request.method == 'GET':
        draft = query.first()
        # Surface older-base drafts without copying their text into the new head.
        others = list(EditorDraft.objects.filter(user=request.user, document=document, branch=branch)
                      .exclude(base_version=base).order_by('-updated_at')
                      .values('base_version_id', 'updated_at')[:20])
        return JsonResponse({'draft': payload(draft) if draft else None, 'other_drafts': others})
    if branch.archived_at or (branch.is_default and document_role(request.user, document) != 'owner'):
        raise PermissionDenied('该分支不可编辑。')
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'JSON_REQUIRED'}, status=415)
    raw = request.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        return JsonResponse({'error': 'CONTENT_TOO_LARGE'}, status=413)
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) - {'action', 'revision', 'content', 'commit_message', 'version_kind'}:
            raise ValueError
        revision = data.get('revision')
        if not isinstance(revision, str) or (revision and str(uuid.UUID(revision)) != revision):
            raise ValueError
        action = data.get('action', 'save')
        if action not in {'save', 'delete'}:
            raise ValueError
        if action == 'save':
            if not all(isinstance(data.get(key), str) for key in ('content', 'commit_message', 'version_kind')):
                raise ValueError
            if len(data['commit_message']) > 300 or data['version_kind'] not in {'patch', 'minor', 'major'}:
                raise ValueError
            for field in ('content', 'commit_message'):
                if '\x00' in data[field]:
                    raise ValueError
                data[field].encode('utf-8')
    except (ValueError, UnicodeDecodeError, RecursionError):
        return JsonResponse({'error': 'INVALID_ARGUMENTS'}, status=400)
    # padif_access_required already holds the document row lock on POST.
    draft = query.select_for_update().first()
    if revision != (str(draft.revision) if draft else ''):
        return JsonResponse({'error': 'DRAFT_CONFLICT'}, status=409)
    if action == 'delete':
        query.delete()
        return JsonResponse({'draft': None})
    if draft is None:
        draft = EditorDraft(user=request.user, document=document, branch=branch, base_version=base)
    else:
        draft.revision = uuid.uuid4()
    for field in ('content', 'commit_message', 'version_kind'):
        setattr(draft, field, data[field])
    draft.save()
    return JsonResponse({'draft': payload(draft)})
