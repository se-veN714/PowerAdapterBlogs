"""Permission-aware security navigation without weakening route authorization."""

from django.conf import settings

from .authn.mfa_session import mfa_required_for_user


def account_security_navigation(request):
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return {
            "can_manage_mfa": False,
            "super_admin_entry_url": "",
        }
    return {
        "can_manage_mfa": mfa_required_for_user(user),
        "super_admin_entry_url": (
            settings.SUPER_ADMIN_EXTERNAL_URL if user.is_superuser else ""
        ),
    }
