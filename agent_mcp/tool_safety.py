"""MCP payload budgets measured after the actual text/structured serialization."""
import json
import hashlib
from typing import Any

from django.http import JsonResponse

MAX_TOOL_RESPONSE_BYTES = 64 * 1024
MAX_NEW_TOOL_INPUT_BYTES = 64 * 1024
MAX_CONTENT_CHUNK_BYTES = 16 * 1024


def canonical_content(content: str) -> str:
    return content.removeprefix('\ufeff').replace('\r\n', '\n').replace('\r', '\n')


def content_hash(content: str) -> str:
    return hashlib.sha256(canonical_content(content).encode('utf-8')).hexdigest()


def contains_nul(value: Any) -> bool:
    """Reject database-invalid text, without rejecting the literal characters \\u0000."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and '\x00' in item:
            return True
    return False


class ToolFailure(Exception):
    """A safe, constant error code; never carry manuscript values into errors."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def payload(self) -> dict:
        recoveries = {
            'OUTPUT_TOO_LARGE': 'Use compare_versions(offset, limit), list_annotations(paginate_replies=true), get_workspace(include_content=false), source ranges or read_content_chunk.',
            'DIFF_TOO_COMPLEX': 'Comparison exceeded the 3-second or complexity budget. Read fixed version chunks or compare smaller writing revisions; do not retry identical expensive input or bypass MCP.',
            'DIFF_BUSY': 'Diff workers are busy. Back off and retry this read; do not create additional connections or bypass MCP.',
            'CONTENT_TOO_LARGE': 'Use smaller exact patches or begin_markdown_upload and its authenticated website file selector. Never extract client credentials.',
            'STALE_BASE_VERSION': 'Read the current branch head and review the changes before creating a new request.',
            'INVALID_TOKEN': 'Use normal client OAuth refresh or ask the user to authorize; never extract client credential files.',
            'STALE_CONTENT': 'Read this source again from the beginning; do not combine chunks from different hashes.',
        }
        result = {'error': self.code, 'message': 'The operation was rejected without completing a new write.',
                  'retryable': self.code in {'DIFF_BUSY', 'DIFF_WORKER_UNAVAILABLE'}}
        if self.code in recoveries:
            result['recovery'] = recoveries[self.code]
        else:
            result['recovery'] = 'Review the arguments, source snapshot and current permissions; do not bypass MCP.'
        return result


def result_payload(result: dict) -> dict:
    return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}],
            'structuredContent': result, 'isError': 'error' in result}


def response_bytes(result: dict, response_id: Any = None) -> bytes:
    return JsonResponse({'jsonrpc': '2.0', 'id': response_id, 'result': result_payload(result)},
                        json_dumps_params={'ensure_ascii': False}).content


def bounded_result(result: dict, response_id: Any = None) -> dict:
    if len(response_bytes(result, response_id)) > MAX_TOOL_RESPONSE_BYTES:
        raise ToolFailure('OUTPUT_TOO_LARGE')
    return result
