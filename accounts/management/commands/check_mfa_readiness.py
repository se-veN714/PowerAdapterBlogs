"""Fail-closed preflight before enabling H2 MFA enforcement."""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from accounts.authn.mfa_services import (
    MfaServiceError,
    _active_key_id,
    _decrypt_seed,
    _keyring,
)
from accounts.models import MfaTotpDevice, MyUser


class Command(BaseCommand):
    help = (
        "Validate privileged-user MFA readiness without printing any secret material."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--acknowledge-recovery-material",
            action="store_true",
            help="Confirm recovery codes are stored offline and break-glass was reviewed.",
        )

    def handle(self, *args, **options):
        if not options["acknowledge_recovery_material"]:
            raise CommandError(
                "Refusing readiness approval without offline recovery-material acknowledgement."
            )
        try:
            keyring = _keyring()
            if _active_key_id() not in keyring:
                raise MfaServiceError("keyring_unavailable")
        except MfaServiceError as exc:
            raise CommandError("MFA keyring is unavailable or invalid.") from exc

        privileged_users = (
            MyUser.objects.filter(is_active=True)
            .filter(
                Q(is_superuser=True)
                | Q(
                    board_memberships__role="manager",
                    board_memberships__is_active=True,
                )
            )
            .distinct()
        )
        if not privileged_users.filter(is_superuser=True).exists():
            raise CommandError(
                "No active superuser exists; enforcement would be unsafe."
            )

        failures = []
        for user in privileged_users.iterator():
            device = MfaTotpDevice.objects.filter(
                user=user,
                status=MfaTotpDevice.Status.ACTIVE,
            ).first()
            if device is None:
                failures.append(f"user_id={user.pk}:active_device_missing")
                continue
            if not device.recovery_codes.filter(used_at__isnull=True).exists():
                failures.append(f"user_id={user.pk}:recovery_codes_exhausted")
                continue
            try:
                _decrypt_seed(device)
            except MfaServiceError:
                failures.append(f"user_id={user.pk}:seed_unavailable")
        if failures:
            raise CommandError("MFA readiness failed: " + ", ".join(failures))

        self.stdout.write(
            self.style.SUCCESS(
                f"MFA readiness passed for {privileged_users.count()} privileged user(s)."
            )
        )
