"""Stateless Streamable HTTP, JSON-response mode, on the existing WSGI stack.

No server-initiated notifications or resumable SSE are advertised. Protocol
messages are validated with the official SDK and interoperability is tested
with its real Streamable HTTP client. No transport session stores user identity.
"""
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from mcp import types
from pydantic import ValidationError

from .config import origin
from .oauth import authenticate
from .tools import TOOLS, call_tool
from .views import quota, transport_allowed

logger = logging.getLogger(__name__)
VERSIONS = ('2025-03-26', '2025-06-18', '2025-11-25')


def rpc(request_id, *, result=None, code=None, message=None, status=200):
    data = {'jsonrpc': '2.0', 'id': request_id}
    if code is not None:
        data['error'] = {'code': code, 'message': message}
    else:
        data['result'] = result
    return JsonResponse(data, status=status)


@csrf_exempt
@never_cache
def endpoint(request):
    if not transport_allowed(request):
        return JsonResponse({'error': 'https_required'}, status=400)
    if request.headers.get('Origin') and request.headers['Origin'] != origin():
        return HttpResponse(status=403)
    scheme, _, raw = request.headers.get('Authorization', '').partition(' ')
    connection = authenticate(raw.strip()) if scheme.lower() == 'bearer' and raw.strip() else None
    if connection is None:
        response = JsonResponse({'error': 'invalid_token'}, status=401)
        response['WWW-Authenticate'] = f'Bearer resource_metadata="{origin()}/.well-known/oauth-protected-resource/padif/mcp/"'
        return response
    if request.method != 'POST':
        response = HttpResponse(status=405)
        response['Allow'] = 'POST'
        return response
    if not quota(request, 'mcp', limit=180):
        response = JsonResponse({'error': 'rate_limited'}, status=429)
        response['Retry-After'] = '60'
        return response
    if request.content_type != 'application/json':
        return HttpResponse(status=415)
    accept = request.headers.get('Accept', '')
    if 'application/json' not in accept or 'text/event-stream' not in accept:
        return HttpResponse(status=406)
    if len(request.body) > 2300000:
        return HttpResponse(status=413)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return rpc(None, code=-32700, message='Parse error', status=400)
    if not isinstance(data, dict) or data.get('jsonrpc') != '2.0' or not isinstance(data.get('method'), str):
        return rpc(None, code=-32600, message='Invalid Request', status=400)
    request_id = data.get('id')
    if 'id' in data and (isinstance(request_id, bool) or not isinstance(request_id, (str, int))):
        return rpc(None, code=-32600, message='Invalid Request', status=400)
    if 'id' not in data:
        if data['method'] in {'notifications/initialized', 'notifications/cancelled'}:
            return HttpResponse(status=202)
        return HttpResponse(status=400)
    if data['method'] != 'initialize' and request.headers.get('MCP-Protocol-Version', '2025-03-26') not in VERSIONS:
        return rpc(request_id, code=-32600, message='Unsupported protocol version', status=400)
    try:
        if data['method'] == 'initialize':
            parsed = types.InitializeRequest.model_validate(data)
            version = parsed.params.protocolVersion
            return rpc(request_id, result={'protocolVersion': version if version in VERSIONS else VERSIONS[-1],
                       'capabilities': {'tools': {'listChanged': False}},
                       'serverInfo': {'name': 'padif-writing', 'version': '1.0.0'},
                       'instructions': 'Use a writing branch. Preserve source lines including blanks. Supply base_version_id and request_id for writes. Main publication requires review in the website.'})
        if data['method'] == 'ping':
            return rpc(request_id, result={})
        if data['method'] == 'tools/list':
            types.ListToolsRequest.model_validate(data)
            return rpc(request_id, result={'tools': [{key: value for key, value in item.items() if key != 'scope'} for item in TOOLS if item['scope'] in connection.scopes]})
        if data['method'] == 'tools/call':
            parsed = types.CallToolRequest.model_validate(data)
            result = call_tool(connection, parsed.params.name, parsed.params.arguments or {})
            return rpc(request_id, result={'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}],
                       'structuredContent': result, 'isError': 'error' in result})
        return rpc(request_id, code=-32601, message='Method not found')
    except ValidationError:
        return rpc(request_id, code=-32602, message='Invalid params')
    except Exception:
        # No traceback containing tool arguments/credentials in client responses.
        logger.error('PAdif MCP operation failed; method=%s', data['method'])
        return rpc(request_id, code=-32603, message='Internal error')
