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
from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import ValidationError
from django.urls import reverse

from PowerAdapterBlogs.base_admin import has_dashboard_access


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
    site_header = 'PowerAdapterBlogs'
    site_title = 'PowerAdapterBlogs 管理后台'
    index_title = '首页'
    login_form = DashboardAuthenticationForm

    def login(self, request, extra_context=None):
        """Default a direct dashboard login to this AdminSite's index."""
        if not request.GET.get(REDIRECT_FIELD_NAME) and not request.POST.get(
            REDIRECT_FIELD_NAME
        ):
            request.GET = request.GET.copy()
            request.GET[REDIRECT_FIELD_NAME] = reverse(f"{self.name}:index")
        return super().login(request, extra_context)

    def has_permission(self, request):
        """dashboard 入口：检查 is_dashboard_user（与 /super_admin/ 的 is_staff 分离）"""
        return has_dashboard_access(request.user)


custom_site = CustomSite(name='cus_admin')
