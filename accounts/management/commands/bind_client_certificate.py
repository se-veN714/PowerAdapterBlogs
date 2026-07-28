from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from accounts.models import MyUser
from accounts.authn.mtls_services import (
    PRODUCTION_CERTIFICATE_PROFILE,
    MtlsServiceError,
    bind_client_certificate,
)


class Command(BaseCommand):
    help = "Bind non-secret mTLS certificate metadata to an active superuser."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--serial", required=True)
        parser.add_argument("--issuer-dn", required=True)
        parser.add_argument("--subject-dn", required=True)
        parser.add_argument(
            "--profile",
            default=PRODUCTION_CERTIFICATE_PROFILE,
            choices=(PRODUCTION_CERTIFICATE_PROFILE,),
            help="Production H3 accepts standard TLS 1.3 mTLS only.",
        )
        parser.add_argument(
            "--expires-at",
            required=True,
            help="Timezone-aware ISO-8601 timestamp.",
        )

    def handle(self, *args, **options):
        try:
            target = MyUser.objects.get(username=options["username"])
            actor = MyUser.objects.get(username=options["actor"])
        except MyUser.DoesNotExist as exc:
            raise CommandError("Target or actor account does not exist.") from exc
        expires_at = parse_datetime(options["expires_at"])
        if expires_at is None:
            raise CommandError("--expires-at must be a valid ISO-8601 timestamp.")
        try:
            binding = bind_client_certificate(
                user=target,
                actor=actor,
                serial_number=options["serial"],
                issuer_dn=options["issuer_dn"],
                subject_dn=options["subject_dn"],
                certificate_profile=options["profile"],
                expires_at=expires_at,
            )
        except MtlsServiceError as exc:
            raise CommandError(f"Certificate binding failed: {exc.reason}.") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Certificate binding created: id={binding.pk} user_id={target.pk}."
            )
        )
