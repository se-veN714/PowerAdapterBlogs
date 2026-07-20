"""Boards 应用的 Django Admin 注册。

Board 模型注册到 custom_site (dashboard)，使用 DashboardAdminMixin 权限控制。
"""

from django.contrib import admin

from PowerAdapterBlogs.base_admin import DashboardAdminMixin
from PowerAdapterBlogs.cus_site import custom_site
from boards.models import Board, BoardMembership
from boards.policies import (
    boards_manageable_by,
    can_access_board_admin,
    can_change_board_settings,
)


@admin.register(Board, site=custom_site)
class BoardAdmin(DashboardAdminMixin, admin.ModelAdmin):
    """首页板块管理。

    行内编辑排序、颜色、启用状态，方便快速调整首页布局。
    """

    list_display = [
        'sort_order', 'name', 'glitch_color_preview',
        'category', 'is_active', 'updated_at',
    ]
    list_display_links = ['name']
    list_editable = ['sort_order']
    list_filter = ['is_active']
    search_fields = ['name', 'slug', 'keywords']
    ordering = ['sort_order']

    fieldsets = (
        ('基本信息', {
            'fields': ('slug', 'name', 'sort_order', 'is_active'),
        }),
        ('内容', {
            'fields': ('description',),
        }),
        ('视觉效果', {
            'fields': ('glitch_color', 'keywords'),
        }),
        ('关联', {
            'fields': ('category',),
        }),
    )

    def has_add_permission(self, request):
        """A new Board implies new frontend code and is superuser-only."""
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        """Deleting a Board changes the site structure and is superuser-only."""
        return request.user.is_active and request.user.is_superuser

    def has_module_permission(self, request):
        return can_access_board_admin(request.user)

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return can_access_board_admin(request.user)
        return can_change_board_settings(request.user, obj)

    def has_change_permission(self, request, obj=None):
        if obj is None:
            return can_access_board_admin(request.user)
        return can_change_board_settings(request.user, obj)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return boards_manageable_by(request.user, queryset)

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return []
        return ["slug", "category", "is_active"]

    def glitch_color_preview(self, obj):
        """在列表中展示颜色预览色块。"""
        return (
            f'<span style="display:inline-block;width:20px;height:20px;'
            f'background:{obj.glitch_color};border-radius:3px;'
            f'border:1px solid rgba(255,255,255,0.15);"></span>'
            f' <code>{obj.glitch_color}</code>'
        )

    glitch_color_preview.short_description = "Glitch 颜色"
    glitch_color_preview.allow_tags = True


@admin.register(BoardMembership)
class BoardMembershipObservationAdmin(admin.ModelAdmin):
    """Super-admin-only, read-only observation of Board memberships.

    Membership writes will be introduced through the reviewed approval flow in
    a later accounts_linear stage. Keeping this view off ``custom_site`` avoids
    exposing cross-Board membership data before scoped querysets exist.
    """

    list_display = ["board", "user", "role", "is_active", "created_by", "created_at"]
    list_filter = ["board", "role", "is_active"]
    search_fields = ["board__name", "board__slug", "user__username", "user__email"]
    list_select_related = ["board", "user", "created_by"]
    ordering = ["board__sort_order", "user__username"]
    readonly_fields = [
        "board",
        "user",
        "role",
        "is_active",
        "created_by",
        "created_at",
    ]

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
