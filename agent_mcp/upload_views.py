"""User-mediated file selection; no tokens, public bytes or rendered manuscripts."""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from padif.models import Document
from padif.permissions import require_document
from . import uploads
from .models import MarkdownUpload
from .tools import call_tool, _live_connection
from .tool_safety import ToolFailure, MAX_NEW_TOOL_INPUT_BYTES
from .views import transport_allowed

logger = logging.getLogger(__name__)


@login_required
@never_cache
def upload_file(request, upload_id):
    if not transport_allowed(request):
        return JsonResponse({'error': 'HTTPS_REQUIRED'}, status=400)
    task = MarkdownUpload.objects.select_related('connection', 'branch').filter(pk=upload_id, user=request.user).first()
    if task is None:
        raise Http404
    connection = task.connection
    try:
        if request.method == 'GET':
            result = call_tool(connection, 'get_markdown_upload_status', {'upload_id': str(upload_id)})
            if 'error' in result:
                return JsonResponse(result, status=403)
            response = render(request, 'pages/accounts/markdown_upload.html', {'upload': result})
            response['X-Content-Type-Options'] = 'nosniff'
            return response
        if request.method != 'POST':
            return JsonResponse({'error': 'METHOD_NOT_ALLOWED'}, status=405)
        if request.content_type != 'application/json':
            return JsonResponse({'error': 'JSON_REQUIRED'}, status=415)
        if int(request.META.get('CONTENT_LENGTH') or 0) > MAX_NEW_TOOL_INPUT_BYTES:
            return JsonResponse({'error': 'CONTENT_TOO_LARGE'}, status=413)
        raw = request.read(MAX_NEW_TOOL_INPUT_BYTES+1)
        if len(raw) > MAX_NEW_TOOL_INPUT_BYTES:
            return JsonResponse({'error': 'CONTENT_TOO_LARGE'}, status=413)
        values = json.loads(raw)
        if not isinstance(values, dict):
            raise ToolFailure('INVALID_ARGUMENTS')
        action = values.pop('action', '')
        if action == 'manifest':
            if set(values) != {'file_name', 'file_size', 'file_sha256'}:
                raise ToolFailure('INVALID_ARGUMENTS')
            with transaction.atomic():
                fresh = _live_connection(connection, lock=True)
                if 'padif:version' not in fresh.scopes:
                    raise ToolFailure('INSUFFICIENT_SCOPE')
                document = Document.objects.select_for_update().get(pk=task.document_id)
                require_document(fresh.user, document, write=True, agent=True, operation='padif:version')
                locked = uploads.get_task(fresh, str(task.pk))
                result = uploads.guard(fresh, locked)
                if result is None:
                    if locked.state not in uploads.ACTIVE:
                        raise ToolFailure('UPLOAD_STATE_CONFLICT')
                    result = uploads.bind_manifest(locked, values)
        elif action == 'chunk':
            result = call_tool(connection, 'append_markdown_chunk', {**values, 'upload_id': str(task.pk)})
        else:
            raise ToolFailure('INVALID_ARGUMENTS')
        return JsonResponse(result, status=400 if 'error' in result else 200)
    except ToolFailure as error:
        return JsonResponse(error.payload(), status=400)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return JsonResponse({'error': 'INVALID_ARGUMENTS'}, status=400)
    except PermissionDenied:
        return JsonResponse({'error': 'DOCUMENT_PERMISSION_DENIED'}, status=403)
    except Http404:
        return JsonResponse({'error': 'NOT_FOUND'}, status=404)
    except Exception:
        # Do not expose request bytes/credentials in a DEBUG traceback or error log.
        logger.error('Private Markdown upload operation failed')
        return JsonResponse({'error': 'UPLOAD_OPERATION_FAILED'}, status=500)
