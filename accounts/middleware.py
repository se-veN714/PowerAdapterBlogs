"""
Middleware that captures request.user into thread-local storage
so that model-layer security checks can identify the acting user.
"""

from .thread_local import set_current_user, clear_current_user


class MtlsAdminMiddleware:
    """Require a trusted, bound client certificate for the system AdminSite."""

    protected_prefix = "/super_admin/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import HttpResponseForbidden, HttpResponseServerError

        from .authn.mtls_services import (
            MtlsServiceError,
            log_request_rejection,
            resolve_client_certificate,
        )

        if not settings.MTLS_ENFORCEMENT_ENABLED or not request.path.startswith(
            self.protected_prefix
        ):
            return self.get_response(request)
        if not settings.MFA_ENFORCEMENT_ENABLED:
            log_request_rejection("mfa_dependency_disabled")
            return HttpResponseServerError("系统后台安全配置未完成。")
        expected_user = request.user if request.user.is_authenticated else None
        try:
            request.client_certificate_binding = resolve_client_certificate(
                request,
                expected_user=expected_user,
            )
        except MtlsServiceError as exc:
            log_request_rejection(exc.reason)
            return HttpResponseForbidden("客户端证书验证失败。")
        return self.get_response(request)


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

        from .authn.mfa_session import (
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
        require_certificate = (
            settings.MTLS_ENFORCEMENT_ENABLED
            and request.path.startswith("/super_admin/")
        )
        if privileged_session_is_valid(
            request,
            require_certificate=require_certificate,
        ):
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
            certificate_binding=getattr(
                request,
                "client_certificate_binding",
                None,
            ),
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
