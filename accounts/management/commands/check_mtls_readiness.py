import ipaddress

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.authn.mtls_services import PRODUCTION_CERTIFICATE_PROFILE
from accounts.models import ClientCertificateBinding, MyUser


class Command(BaseCommand):
    help = "Check H3 application-side mTLS readiness without reading certificate keys."

    def add_arguments(self, parser):
        acknowledgements = (
            (
                "--acknowledge-proxy-boundary",
                "Confirm Nginx header replacement and the private upstream were tested.",
            ),
            (
                "--acknowledge-client-ca",
                "Confirm the Client CA key is offline and no private key is in the repository.",
            ),
            (
                "--acknowledge-revocation",
                "Confirm CRL deployment and Django binding revocation were tested.",
            ),
            (
                "--acknowledge-break-glass",
                "Confirm console/SSH recovery and rollback were rehearsed.",
            ),
            (
                "--acknowledge-openssl-4",
                "Confirm Nginx and CA tooling report a supported OpenSSL 4.0.x patch release.",
            ),
        )
        for flag, help_text in acknowledgements:
            parser.add_argument(flag, action="store_true", help=help_text)

    def handle(self, *args, **options):
        required_acknowledgements = (
            "acknowledge_proxy_boundary",
            "acknowledge_client_ca",
            "acknowledge_revocation",
            "acknowledge_break_glass",
            "acknowledge_openssl_4",
        )
        missing_acknowledgements = [
            name for name in required_acknowledgements if not options[name]
        ]
        if missing_acknowledgements:
            flags = ", ".join(
                f"--{name.replace('_', '-')}" for name in missing_acknowledgements
            )
            raise CommandError(f"Refusing readiness check; missing: {flags}.")
        failures = []
        host = getattr(settings, "MTLS_ADMIN_HOST", "")
        secret = getattr(settings, "MTLS_PROXY_AUTH_SECRET", "")
        networks = getattr(settings, "MTLS_TRUSTED_PROXY_NETWORKS", ())
        profile = getattr(settings, "MTLS_CERTIFICATE_PROFILE", "")
        trust_unix_socket = getattr(settings, "MTLS_TRUST_UNIX_SOCKET_PROXY", False)
        if not isinstance(host, str) or not host.strip():
            failures.append("admin_host_missing")
        if not isinstance(secret, str) or len(secret) < 32:
            failures.append("proxy_auth_secret_invalid")
        try:
            parsed_networks = tuple(
                ipaddress.ip_network(network, strict=False) for network in networks
            )
        except (TypeError, ValueError):
            parsed_networks = ()
        if not parsed_networks and trust_unix_socket is not True:
            failures.append("trusted_proxy_network_missing")
        if profile != PRODUCTION_CERTIFICATE_PROFILE:
            failures.append("certificate_profile_invalid")

        superusers = MyUser.objects.filter(is_active=True, is_superuser=True)
        if not superusers.exists():
            failures.append("active_superuser_missing")
        now = timezone.now()
        for user_id in superusers.values_list("pk", flat=True):
            if not ClientCertificateBinding.objects.filter(
                user_id=user_id,
                status=ClientCertificateBinding.Status.ACTIVE,
                expires_at__gt=now,
                certificate_profile=profile,
            ).exists():
                failures.append(f"user_id={user_id}:active_binding_missing")
        if failures:
            for failure in failures:
                self.stderr.write(f"FAIL {failure}")
            raise CommandError("mTLS readiness failed.")
        self.stdout.write(
            self.style.SUCCESS(
                f"mTLS readiness passed for {superusers.count()} superuser(s)."
            )
        )
