"""OAuth Toolkit extension points, sharing existing accounts and PAdif permissions."""
import hashlib
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone
from oauth2_provider.models import AccessToken, RefreshToken
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauthlib.oauth2.rfc6749.errors import CustomOAuth2Error

from accounts.agent_auth import _audit_agent_event
from .access import can_use_agent
from .config import resource
from .models import Connection


def audit(event, connection, actor=None):
    _audit_agent_event(event_type=event, actor=actor or connection.user,
                       target_type='mcp_connection', target_id=connection.pk,
                       change={'scopes': connection.scopes}, source='padif_mcp')


@transaction.atomic
def revoke_connection(connection, actor=None, event='agent.mcp.revoked'):
    locked = Connection.objects.select_for_update().get(pk=connection.pk)
    if locked.revoked_at is None:
        locked.revoked_at = timezone.now()
        locked.save(update_fields=['revoked_at'])
        RefreshToken.revoke_family(locked.family)
        audit(event, locked, actor)


class PadifOAuthValidator(OAuth2Validator):
    def validate_client_id(self, client_id, request, *args, **kwargs):
        valid = super().validate_client_id(client_id, request, *args, **kwargs)
        # Explicit consent and pre-registered public Authorization Code clients only.
        return valid and request.client.client_type == 'public' and request.client.authorization_grant_type == 'authorization-code' and not request.client.skip_authorization

    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        # DOT allows variable loopback ports; our pre-registration contract is exact.
        uri = urlsplit(redirect_uri)
        secure = uri.scheme == 'https' or (uri.scheme == 'http' and uri.hostname in {'127.0.0.1', 'localhost', '::1'})
        return secure and redirect_uri in request.client.redirect_uris.split() and super().validate_redirect_uri(client_id, redirect_uri, request, *args, **kwargs)

    def validate_grant_type(self, client_id, grant_type, client, request, *args, **kwargs):
        return (grant_type in {'authorization_code', 'refresh_token'} and client.client_type == 'public'
                and not client.skip_authorization and super().validate_grant_type(client_id, grant_type, client, request, *args, **kwargs))

    def validate_code(self, client_id, code, client, request, *args, **kwargs):
        return super().validate_code(client_id, code, client, request, *args, **kwargs) and can_use_agent(request.user)

    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        valid = super().validate_refresh_token(refresh_token, client, request, *args, **kwargs)
        checksum = hashlib.sha256(refresh_token.encode()).hexdigest()
        rt = RefreshToken.objects.filter(token_checksum=checksum).first()
        connection = Connection.objects.filter(family=rt.token_family).first() if rt else None
        if not valid:
            if connection and rt.revoked and connection.revoked_at is None:
                revoke_connection(connection, event='agent.mcp.refresh_replayed')
            return False
        return bool(connection and connection.revoked_at is None and connection.expires_at > timezone.now() and can_use_agent(request.user))

    def _save_bearer_token(self, token, request, *args, **kwargs):
        super()._save_bearer_token(token, request, *args, **kwargs)
        access = AccessToken.objects.get(token_checksum=hashlib.sha256(token['access_token'].encode()).hexdigest())
        rt = RefreshToken.objects.get(access_token=access)
        connection, created = Connection.objects.get_or_create(family=rt.token_family, defaults={
            'user': request.user, 'application': request.client,
            'scopes': token['scope'].split(), 'expires_at': timezone.now() + timedelta(days=7),
        })
        if created:
            audit('agent.mcp.authorized', connection)
        elif connection.scopes != token['scope'].split():
            connection.scopes = token['scope'].split()
            connection.save(update_fields=['scopes'])

    def _check_and_set_request_resource(self, request):
        super()._check_and_set_request_resource(request)
        if request.resource != [resource()]:
            raise CustomOAuth2Error(error='invalid_target', description='Use the PAdif MCP resource identifier.')

    def revoke_token(self, token, token_type_hint, request, *args, **kwargs):
        checksum = hashlib.sha256(token.encode()).hexdigest()
        rt = RefreshToken.objects.filter(token_checksum=checksum, application=request.client).first()
        if rt is None:
            access = AccessToken.objects.filter(token_checksum=checksum, application=request.client).first()
            rt = RefreshToken.objects.filter(access_token=access).first() if access else None
        if rt:
            connection = Connection.objects.filter(family=rt.token_family).first()
            if connection:
                revoke_connection(connection)
        return super().revoke_token(token, token_type_hint, request, *args, **kwargs)


def authenticate(raw):
    access = AccessToken.objects.select_related('user', 'application').filter(
        token_checksum=hashlib.sha256(raw.encode()).hexdigest(), expires__gt=timezone.now()).first()
    if access is None or access.resource != [resource()] or not can_use_agent(access.user):
        return None
    rt = RefreshToken.objects.filter(access_token=access, revoked__isnull=True).first()
    connection = Connection.objects.select_related('user', 'application').filter(
        family=rt.token_family, revoked_at__isnull=True, expires_at__gt=timezone.now()).first() if rt else None
    if connection is None:
        return None
    # A refreshed request must not retain scopes removed during refresh.
    connection.scopes = access.scope.split()
    Connection.objects.filter(pk=connection.pk).update(last_used_at=timezone.now())
    return connection
