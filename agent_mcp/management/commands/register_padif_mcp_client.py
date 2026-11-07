from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError
from oauth2_provider.models import Application


class Command(BaseCommand):
    help = 'Pre-register a public PKCE MCP client with exact callback URLs; never outputs a secret.'

    def add_arguments(self, parser):
        parser.add_argument('--client-id', required=True)
        parser.add_argument('--name', required=True)
        parser.add_argument('--redirect-uri', action='append', required=True)

    def handle(self, *args, **options):
        redirects = options['redirect_uri']
        for value in redirects:
            uri = urlsplit(value)
            if not uri.hostname or uri.username or uri.password or uri.fragment or '*' in value or any(char.isspace() for char in value):
                raise CommandError('Invalid callback URL.')
            if uri.scheme != 'https' and not (uri.scheme == 'http' and uri.hostname in {'localhost', '127.0.0.1', '::1'}):
                raise CommandError('Callbacks require HTTPS, except loopback HTTP callbacks.')
        values = {'name': options['name'], 'redirect_uris': ' '.join(redirects),
                  'client_type': Application.CLIENT_PUBLIC,
                  'authorization_grant_type': Application.GRANT_AUTHORIZATION_CODE,
                  'skip_authorization': False}
        client, created = Application.objects.get_or_create(client_id=options['client_id'], defaults=values)
        if not created and any(getattr(client, key) != value for key, value in values.items()):
            raise CommandError('Client ID already has different settings; review it in Admin.')
        self.stdout.write(self.style.SUCCESS(f'PKCE client {client.client_id}: {"created" if created else "unchanged"}'))
