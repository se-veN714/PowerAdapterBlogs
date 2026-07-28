"""
Middleware that captures request.user into thread-local storage
so that model-layer security checks can identify the acting user.
"""

from .thread_local import set_current_user, clear_current_user


class MfaPrivilegeMiddleware:
    """Require a fresh H2b privileged session at both administration shells."""

    protected_prefixes = ("/dashboard/", "/super_admin/")
    recovery_paths = {
        "/accounts/security/mfa/",
        "/accounts/security/mfa/confirm/",
        "/accounts/logout/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.contrib.auth import logout
        from django.shortcuts import redirect
        from django.urls import reverse

        from .mfa_session import (
            active_mfa_device,
            issue_pending_challenge,
            mfa_required_for_user,
            privileged_session_is_valid,
            recovery_session_is_valid,
        )

        if not settings.MFA_ENFORCEMENT_ENABLED:
            return self.get_response(request)

        had_recovery_state = "accounts.mfa.recovery" in request.session
        recovery_valid = recovery_session_is_valid(request)
        if had_recovery_state and not recovery_valid:
            logout(request)
            return redirect("accounts:login")
        if recovery_valid and request.path not in self.recovery_paths:
            return redirect("accounts:mfa-settings")

        if not request.path.startswith(self.protected_prefixes):
            return self.get_response(request)
        if not request.user.is_authenticated or not mfa_required_for_user(request.user):
            return self.get_response(request)
        if privileged_session_is_valid(request):
            return self.get_response(request)
        if active_mfa_device(request.user) is None:
            return redirect("accounts:mfa-settings")

        backend = request.session.get(
            "_auth_user_backend",
            "django.contrib.auth.backends.ModelBackend",
        )
        issue_pending_challenge(
            request,
            user=request.user,
            backend=backend,
            target=request.get_full_path(),
        )
        return redirect(reverse("accounts:mfa-challenge"))


class RequestUserMiddleware:
    """Store request.user in thread-local for the duration of the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_user(getattr(request, "user", None))
        try:
            response = self.get_response(request)
        finally:
            clear_current_user()
        return response
