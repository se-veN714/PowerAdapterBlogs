import json
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views import View
from oauth2_provider.models import Application, Grant, RefreshToken
from oauth2_provider.views import AuthorizationView, TokenView, RevokeTokenView

from .config import SCOPES, origin, resource
from .models import Connection
from .oauth import revoke_connection
from .access import can_use_agent


def transport_allowed(request):
    parsed = urlsplit(origin())
    return request.is_secure() or (settings.DEBUG and parsed.hostname in {'localhost', '127.0.0.1', '::1'} and request.get_host() == parsed.netloc)


def quota(request, kind, limit=60):
    # Existing deployment supplies the client IP via ClientMetaMiddleware.
    from hashlib import sha256
    identity = str(getattr(request, 'client_ip', request.META.get('REMOTE_ADDR', 'unknown')))
    key = 'mcp-quota:' + kind + ':' + sha256(identity.encode()).hexdigest()
    if cache.add(key, 1, timeout=60):
        return True
    try:
        return cache.incr(key) <= limit
    except ValueError:
        return False


class OAuthTransportMixin:
    rate_limit = 60

    def dispatch(self, request, *args, **kwargs):
        if not transport_allowed(request):
            return JsonResponse({'error': 'https_required'}, status=400)
        if not quota(request, self.__class__.__name__, limit=self.rate_limit):
            response = JsonResponse({'error': 'rate_limited'}, status=429)
            response['Retry-After'] = '60'
            return response
        response = super().dispatch(request, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        response['Pragma'] = 'no-cache'
        return response


@method_decorator(never_cache, name='dispatch')
class PadifAuthorizationView(OAuthTransportMixin, AuthorizationView):
    template_name = 'pages/accounts/mcp_authorize.html'
    signed_fields = ('client_id', 'redirect_uri', 'scope', 'state', 'response_type', 'code_challenge', 'code_challenge_method', 'resource')

    def get(self, request, *args, **kwargs):
        # A client cannot bypass our consent page using approval_prompt=auto.
        request.GET = request.GET.copy()
        request.GET['approval_prompt'] = 'force'
        return super().get(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not can_use_agent(request.user):
            from django.shortcuts import render
            return render(request, 'pages/accounts/agent_access_required.html', status=403)
        data = request.POST if request.method == 'POST' else request.GET
        if data.get('response_type') != 'code' or not data.get('state'):
            return JsonResponse({'error': 'invalid_request', 'error_description': 'Use code flow and state.'}, status=400)
        if data.getlist('resource') != [resource()]:
            return JsonResponse({'error': 'invalid_target'}, status=400)
        if data.get('code_challenge_method') != 'S256' or not re.fullmatch(r'[A-Za-z0-9_-]{43}', data.get('code_challenge', '')):
            return JsonResponse({'error': 'invalid_request', 'error_description': 'S256 PKCE is required.'}, status=400)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not context.get('error'):
            form = context['form']
            values = {name: form[name].value() or '' for name in self.signed_fields}
            context['consent'] = signing.dumps(values, salt='padif-mcp-consent')
            context['scope_options'] = [(scope, SCOPES[scope]) for scope in values['scope'].split() if scope in SCOPES]
            from .presentation import consent_context
            context.update(consent_context(self.request.user))
        return context

    def form_valid(self, form):
        try:
            signed = signing.loads(self.request.POST.get('consent', ''), salt='padif-mcp-consent', max_age=600)
        except signing.BadSignature:
            return JsonResponse({'error': 'invalid_request', 'error_description': 'Reload the authorization page.'}, status=400)
        if any((form.cleaned_data.get(name) or '') != signed[name] for name in self.signed_fields):
            return JsonResponse({'error': 'invalid_request'}, status=400)
        if form.cleaned_data['allow']:
            approved = self.request.POST.getlist('approved_scope')
            if not approved or not set(approved).issubset(signed['scope'].split()):
                return JsonResponse({'error': 'invalid_scope'}, status=400)
            form.cleaned_data['scope'] = ' '.join(sorted(set(approved)))
        return super().form_valid(form)


@method_decorator(csrf_exempt, name='dispatch')
class PadifTokenView(OAuthTransportMixin, TokenView):
    def post(self, request, *args, **kwargs):
        # Consistent lock order with disconnect and writes: connection before
        # refresh tokens. Also serialize concurrent exchanges of the same code.
        from hashlib import sha256
        from .access import lock_identity
        with transaction.atomic():
            if request.POST.get('grant_type') == 'refresh_token':
                checksum = sha256(request.POST.get('refresh_token', '').encode()).hexdigest()
                rt = RefreshToken.objects.filter(token_checksum=checksum).first()
                if rt:
                    lock_identity(rt.user_id)
                    Connection.objects.select_for_update().filter(family=rt.token_family).first()
            elif request.POST.get('grant_type') == 'authorization_code':
                grant_user = Grant.objects.filter(code=request.POST.get('code', '')).values_list('user_id', flat=True).first()
                if grant_user:
                    lock_identity(grant_user)
                Grant.objects.select_for_update().filter(code=request.POST.get('code', '')).first()
            return super().post(request, *args, **kwargs)


@method_decorator(csrf_exempt, name='dispatch')
class PadifRevokeView(OAuthTransportMixin, RevokeTokenView):
    pass


@method_decorator(csrf_exempt, name='dispatch')
class PadifRegistrationView(OAuthTransportMixin, View):
    """RFC 7591 public-client registration; never issues a user access token.

    Use DOT's Application model/validators and existing token endpoints. Client
    configuration management (RFC 7592) is not exposed, so no management token
    or URI is advertised. Unknown metadata cannot set model/permission fields.
    """
    rate_limit = 10

    def post(self, request):
        def invalid(message, error='invalid_client_metadata'):
            return JsonResponse({'error': error, 'error_description': message}, status=400)

        if request.content_type != 'application/json':
            return invalid('Use application/json.')
        if len(request.body) > 16384:
            return HttpResponse(status=413)
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return invalid('Request body must be a JSON object.')
        if not isinstance(data, dict):
            return invalid('Request body must be a JSON object.')
        name = data.get('client_name', 'Writing Agent')
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            return invalid('client_name must be a nonempty string, up to 120 characters.')
        redirects = data.get('redirect_uris')
        if not isinstance(redirects, list) or not 1 <= len(redirects) <= 4:
            return invalid('Provide 1 to 4 exact callback URLs.', 'invalid_redirect_uri')
        for value in redirects:
            if not isinstance(value, str) or len(value) > 2048 or '*' in value or any(char.isspace() for char in value):
                return invalid('Invalid callback URL.', 'invalid_redirect_uri')
            try:
                uri = urlsplit(value)
                port = uri.port
            except ValueError:
                return invalid('Invalid callback URL.', 'invalid_redirect_uri')
            if not uri.hostname or uri.username or uri.password or uri.fragment or port == 0:
                return invalid('Invalid callback URL.', 'invalid_redirect_uri')
            if uri.scheme != 'https' and not (uri.scheme == 'http' and uri.hostname in {'localhost', '127.0.0.1', '::1'}):
                return invalid('Callbacks require HTTPS, except loopback HTTP.', 'invalid_redirect_uri')
        grants = data.get('grant_types', ['authorization_code'])
        responses = data.get('response_types', ['code'])
        if (not isinstance(grants, list) or not all(isinstance(value, str) for value in grants)
                or 'authorization_code' not in grants or not set(grants).issubset({'authorization_code', 'refresh_token'})):
            return invalid('Only authorization_code and refresh_token are supported.')
        if responses != ['code'] or data.get('token_endpoint_auth_method', 'none') != 'none':
            return invalid('Only public Authorization Code clients (auth method none) are supported.')
        scopes = data.get('scope', ' '.join(SCOPES))
        if not isinstance(scopes, str) or not scopes.split() or not set(scopes.split()).issubset(SCOPES):
            return invalid('Unsupported scopes.')
        application = Application(name=name.strip(), redirect_uris=' '.join(dict.fromkeys(redirects)),
            client_type=Application.CLIENT_PUBLIC, authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            registration_source=Application.RegistrationSource.DCR, skip_authorization=False, user=None)
        try:
            application.full_clean()
        except ValidationError:
            return invalid('Invalid client metadata or callback URL.')
        application.save()
        return JsonResponse({
            'client_id': application.client_id, 'client_id_issued_at': int(application.created.timestamp()),
            'client_name': application.name, 'redirect_uris': application.redirect_uris.split(),
            'grant_types': list(dict.fromkeys(grants)), 'response_types': ['code'],
            'token_endpoint_auth_method': 'none', 'scope': ' '.join(sorted(set(scopes.split()))),
        }, status=201)


def server_metadata(request):
    root = origin()
    return JsonResponse({
        'issuer': root,
        'authorization_endpoint': root + '/accounts/agent/oauth/authorize/',
        'token_endpoint': root + '/accounts/agent/oauth/token/',
        'revocation_endpoint': root + '/accounts/agent/oauth/revoke/',
        'registration_endpoint': root + '/accounts/agent/oauth/register/',
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'token_endpoint_auth_methods_supported': ['none'],
        'revocation_endpoint_auth_methods_supported': ['none'],
        'code_challenge_methods_supported': ['S256'],
        'scopes_supported': list(SCOPES),
        'client_id_metadata_document_supported': False,
    })


def resource_metadata(request):
    return JsonResponse({'resource': resource(), 'resource_name': 'PAdif Writing',
                         'authorization_servers': [origin()], 'scopes_supported': list(SCOPES),
                         'bearer_methods_supported': ['header']})


@login_required
@never_cache
def disconnect(request, connection_id):
    if request.method != 'POST':
        return HttpResponse(status=405)
    connection = Connection.objects.filter(pk=connection_id, user=request.user).first()
    if connection:
        revoke_connection(connection, request.user)
    return redirect('accounts:agent-token-management')
