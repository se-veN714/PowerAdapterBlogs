# -*- coding: utf-8 -*-
# @File    : cus_site.py
# @Time    : 2025/2/20 01:49
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了自定义dashboard功能的类和函数。
"""

from urllib.parse import urlencode

from django.conf import settings
from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db.models.base import ModelBase
from django.shortcuts import redirect
from django.urls import reverse

from PowerAdapterBlogs.base_admin import has_dashboard_access


DASHBOARD_MODEL_ALLOWLIST = frozenset(
    {
        "admin.logentry",
        "blogs.category",
        "blogs.post",
        "blogs.postrevision",
        "blogs.postworkflowevent",
        "blogs.tag",
    }
)


class DashboardAuthenticationForm(AdminAuthenticationForm):
    """Authenticate custom-dashboard users without requiring ``is_staff``."""

    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "invalid_login": "请输入正确的工作台账户用户名和密码。注意两者均区分大小写。",
    }

    def confirm_login_allowed(self, user):
        if not has_dashboard_access(user):
            raise ValidationError(
                self.error_messages["invalid_login"],
                code="invalid_login",
            )


# here put the import lib
class CustomSite(AdminSite):
    site_header = "PowerAdapterBlogs"
    site_title = "PowerAdapterBlogs 管理后台"
    index_title = "首页"
    login_form = DashboardAuthenticationForm

    def register(self, model_or_iterable, admin_class=None, **options):
        """Reject accidental expansion of the reduced-superuser dashboard."""
        models = (
            (model_or_iterable,)
            if isinstance(model_or_iterable, ModelBase)
            else tuple(model_or_iterable)
        )
        unexpected = sorted(
            model._meta.label_lower.lower()
            for model in models
            if model._meta.label_lower.lower() not in DASHBOARD_MODEL_ALLOWLIST
        )
        if unexpected:
            raise ImproperlyConfigured(
                "Models are not approved for /dashboard/: "
                + ", ".join(unexpected)
            )
        return super().register(model_or_iterable, admin_class, **options)

    def login(self, request, extra_context=None):
        """Default a direct dashboard login to this AdminSite's index."""
        if settings.MFA_ENFORCEMENT_ENABLED and not request.user.is_authenticated:
            target = (
                request.GET.get(REDIRECT_FIELD_NAME)
                or request.POST.get(REDIRECT_FIELD_NAME)
                or reverse(f"{self.name}:index")
            )
            return redirect(
                f"{reverse('accounts:login')}?{urlencode({REDIRECT_FIELD_NAME: target})}"
            )
        if not request.GET.get(REDIRECT_FIELD_NAME) and not request.POST.get(
            REDIRECT_FIELD_NAME
        ):
            request.GET = request.GET.copy()
            request.GET[REDIRECT_FIELD_NAME] = reverse(f"{self.name}:index")
        return super().login(request, extra_context)

    def has_permission(self, request):
        """dashboard 入口：检查 is_dashboard_user（与 /super_admin/ 的 is_staff 分离）"""
        return has_dashboard_access(request.user)


custom_site = CustomSite(name="cus_admin")
