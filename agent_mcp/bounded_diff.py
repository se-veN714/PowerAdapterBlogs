"""Authorized MCP comparison with a killable wall-time/complexity boundary."""
import json
import subprocess
import sys
import time
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any

from django.http import Http404

from padif import api
from padif.core.differ import segment
from padif.models import Version
from .long_documents import canonical_content
from .tool_safety import MAX_TOOL_RESPONSE_BYTES, ToolFailure, response_bytes
from . import uploads

DIFF_TIMEOUT_SECONDS = 3.0
MAX_SENTENCES = 10000
MAX_ALIGNMENT_CELLS = 4000000
MAX_CHARACTER_CELLS = 4000000
_WORKERS = BoundedSemaphore(2)


def _preflight(old: str, new: str) -> None:
    if any(len(text.encode('utf-8')) > 2*1024*1024 for text in (old, new)):
        raise ToolFailure('DIFF_TOO_COMPLEX')
    before, after = segment(old), segment(new)
    if (max(len(before), len(after)) > MAX_SENTENCES or len(before)*len(after) > MAX_ALIGNMENT_CELLS
            or max(map(len, before), default=0)*max(map(len, after), default=0) > MAX_CHARACTER_CELLS):
        raise ToolFailure('DIFF_TOO_COMPLEX')


def run_worker(payload: dict, timeout_seconds: float) -> dict:
    """subprocess.run kills and waits for the worker on timeout; never use a thread future."""
    if timeout_seconds <= 0:
        raise ToolFailure('DIFF_TOO_COMPLEX')
    try:
        completed = subprocess.run([sys.executable, '-m', 'agent_mcp.diff_worker'],
            input=json.dumps(payload, ensure_ascii=False).encode('utf-8'), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, cwd=Path(__file__).resolve().parent.parent,
            timeout=max(0.001, timeout_seconds), check=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired as error:
        raise ToolFailure('DIFF_TOO_COMPLEX') from error
    except OSError as error:
        raise ToolFailure('DIFF_WORKER_UNAVAILABLE') from error
    if completed.returncode or len(completed.stdout) > MAX_TOOL_RESPONSE_BYTES:
        raise ToolFailure('DIFF_WORKER_FAILED')
    try:
        result = json.loads(completed.stdout)
    except (ValueError, UnicodeDecodeError) as error:
        raise ToolFailure('DIFF_WORKER_FAILED') from error
    if 'error' in result:
        raise ToolFailure(result['error'])
    return result


def compare_versions(values: dict, response_id: Any = None, *, connection=None) -> dict:
    if ('to_version' in values) == ('to_upload_id' in values):
        raise ToolFailure('INVALID_ARGUMENTS')
    versions = Version.objects.filter(document_id=values['document_id'],
        pk__in=[values['from_version'], values.get('to_version', values['from_version'])]).select_related('branch', 'created_by')
    by_id = {version.pk: version for version in versions}
    if any(pk not in by_id for pk in (values['from_version'], values.get('to_version', values['from_version']))):
        raise Http404
    old = by_id[values['from_version']]
    new = by_id.get(values.get('to_version'))
    started = time.monotonic()
    before = canonical_content(old.content)
    after = uploads.read_staged(connection, values['to_upload_id']) if new is None else canonical_content(new.content)
    _preflight(before, after)
    paged = 'offset' in values or 'limit' in values
    offset, limit = values.get('offset', 0), values.get('limit', 20) if paged else None
    if not _WORKERS.acquire(blocking=False):
        raise ToolFailure('DIFF_BUSY')
    try:
        computed = run_worker({'old': before, 'new': after, 'old_id': old.pk, 'new_id': new.pk if new else values['to_upload_id'], 'new_kind': 'version_markdown' if new else 'upload_markdown',
            'offset': offset, 'limit': limit, 'paged': paged}, DIFF_TIMEOUT_SECONDS-(time.monotonic()-started))
    finally:
        _WORKERS.release()
    total = computed.pop('total_ops')
    result = {'diff': {'from_version': api._version_payload(old), 'to_version': api._version_payload(new) if new else None, **computed}}
    if new is None:
        result['diff']['to_upload_id'] = values['to_upload_id']
    if paged:
        result['diff'].update(offset=offset, total_ops=total, ops_complete=offset == 0 and len(computed['ops']) == total,
            next_offset=offset+len(computed['ops']) if offset+len(computed['ops']) < total else None)
        while len(response_bytes(result, response_id)) > MAX_TOOL_RESPONSE_BYTES and len(computed['ops']) > 1:
            computed['ops'].pop()
            result['diff']['next_offset'] = offset+len(computed['ops'])
            result['diff']['ops_complete'] = False
    return result
