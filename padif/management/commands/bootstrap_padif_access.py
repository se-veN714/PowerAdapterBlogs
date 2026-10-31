from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction


class Command(BaseCommand):
    help = "Create the PAdifUsers group, attach use_padif, and optionally add users."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--user",
            action="append",
            default=[],
            dest="users",
            help="Username to add; may be repeated.",
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        try:
            permission = Permission.objects.get(
                content_type__app_label="padif",
                codename="use_padif",
            )
        except Permission.DoesNotExist as exc:
            raise CommandError("PAdif permission is missing; run migrate first.") from exc

        group, created = Group.objects.get_or_create(name="PAdifUsers")
        group.permissions.add(permission)
        User = get_user_model()
        added: list[str] = []
        for username in options["users"]:
            try:
                user = User._default_manager.get(username=username)
            except User.DoesNotExist as exc:
                raise CommandError(f"User does not exist: {username}") from exc
            user.groups.add(group)
            added.append(username)

        state = "created" if created else "updated"
        suffix = f"; users: {', '.join(added)}" if added else ""
        self.stdout.write(self.style.SUCCESS(f"PAdifUsers {state}{suffix}"))
