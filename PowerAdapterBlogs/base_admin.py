# -*- coding: utf-8 -*-
# @File    : base_admin.py
# @Time    : 2025/2/20 02:18
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了基本用户owner字段功能的类和函数。
"""

# here put the import lib
from django.contrib import admin


def has_dashboard_access(user):
    """Return whether a user may enter the custom dashboard shell."""
    return user.is_active and (user.is_dashboard_user or user.is_superuser)


class BaseOwnerAdmin(admin.ModelAdmin):
    """
    1. 用于补充文章、分类、标签、侧边栏、友链这些 Model 的 owner 字段
    2. 用于针对 queryset 过滤当前用户的数据
    """

    def get_queryset(self, request):
        qs = super(BaseOwnerAdmin, self).get_queryset(request)
        return qs.filter(owner=request.user)

    def save_model(self, request, obj, form, change):
        obj.owner = request.user
        return super(BaseOwnerAdmin, self).save_model(request, obj, form, change)


class DashboardAdminMixin:
    """
    用于 custom_site (/dashboard/) 注册的 Admin 类的权限 mixin。

    Django ModelAdmin 默认权限检查基于 is_staff，但 /dashboard/ 入口的
    权限检查应基于 is_dashboard_user。本 mixin 将 has_module_permission、
    has_view_permission、has_change_permission、has_add_permission 全部
    切换到 is_dashboard_user。

    删除权限仍保留给 superuser，确保日志/用户等重要数据不会被误删。

    get_queryset() 直接调用 ModelAdmin 实现，跳过 BaseOwnerAdmin 的
    owner 过滤——dashboard 用户需要看到所有内容而非仅自己的记录。
    """

    def has_module_permission(self, request):
        return has_dashboard_access(request.user)

    def has_view_permission(self, request, obj=None):
        return has_dashboard_access(request.user)

    def has_change_permission(self, request, obj=None):
        return has_dashboard_access(request.user)

    def has_add_permission(self, request):
        return has_dashboard_access(request.user)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_queryset(self, request):
        """dashboard 用户应看到所有数据，不受 BaseOwnerAdmin 的 owner 过滤限制"""
        return admin.ModelAdmin.get_queryset(self, request)

