"""Authentication signals for privileged single-session enforcement."""

from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from django.dispatch import receiver

PRIVILEGED_SESSION_VERSION_KEY = "accounts.privileged_session_version"


def requires_privileged_single_session(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and (
            getattr(user, "is_superuser", False)
            or getattr(user, "is_dashboard_user", False)
        )
    )


@receiver(user_logged_in, dispatch_uid="accounts.rotate_privileged_session")
def rotate_privileged_session_version(sender, request, user, **kwargs):
    """Make the newest privileged login the only accepted browser session."""
    if request is None or not requires_privileged_single_session(user):
        return
    with transaction.atomic():
        locked_user = sender.objects.select_for_update().only(
            "privileged_session_version"
        ).get(pk=user.pk)
        next_version = locked_user.privileged_session_version + 1
        sender.objects.filter(pk=user.pk).update(
            privileged_session_version=next_version
        )
    user.privileged_session_version = next_version
    request.session[PRIVILEGED_SESSION_VERSION_KEY] = next_version
