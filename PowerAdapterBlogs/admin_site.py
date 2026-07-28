"""Admin-site boundaries for privileged system administration."""

from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode


def has_system_admin_access(user):
    """Return whether ``user`` may enter the system administration site."""
    return user.is_active and user.is_superuser


class SuperuserAuthenticationForm(AdminAuthenticationForm):
    """Reject non-superusers before an admin session is established."""

    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "invalid_login": "请输入正确的超级管理员用户名和密码。注意两者均区分大小写。",
    }

    def confirm_login_allowed(self, user):
        if not has_system_admin_access(user):
            raise ValidationError(
                self.error_messages["invalid_login"],
                code="invalid_login",
            )


class SuperuserAdminSite(AdminSite):
    """Default Django admin site restricted to active superusers."""

    login_form = SuperuserAuthenticationForm

    def login(self, request, extra_context=None):
        if settings.MFA_ENFORCEMENT_ENABLED and not request.user.is_authenticated:
            target = (
                request.GET.get(REDIRECT_FIELD_NAME)
                or request.POST.get(REDIRECT_FIELD_NAME)
                or reverse(f"{self.name}:index")
            )
            return redirect(
                f"{reverse('accounts:login')}?{urlencode({REDIRECT_FIELD_NAME: target})}"
            )
        return super().login(request, extra_context)

    def has_permission(self, request):
        return has_system_admin_access(request.user)
