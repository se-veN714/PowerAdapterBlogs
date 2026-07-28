from django.core.management.base import BaseCommand, CommandError

from accounts.models import ClientCertificateBinding, MyUser
from accounts.authn.mtls_services import MtlsServiceError, revoke_client_certificate


class Command(BaseCommand):
    help = "Revoke one mTLS client-certificate binding and invalidate its sessions."

    def add_arguments(self, parser):
        parser.add_argument("--binding-id", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument(
            "--reason",
            required=True,
            choices=("expired", "rotated", "lost", "suspected_compromise"),
        )

    def handle(self, *args, **options):
        try:
            binding = ClientCertificateBinding.objects.get(pk=options["binding_id"])
            actor = MyUser.objects.get(username=options["actor"])
        except (ClientCertificateBinding.DoesNotExist, MyUser.DoesNotExist) as exc:
            raise CommandError("Certificate binding or actor does not exist.") from exc
        try:
            revoked = revoke_client_certificate(
                binding=binding,
                actor=actor,
                reason=options["reason"],
            )
        except MtlsServiceError as exc:
            raise CommandError(f"Certificate revocation failed: {exc.reason}.") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Certificate binding revoked: id={revoked.pk} user_id={revoked.user_id}."
            )
        )
