"""Boards 应用的 Django Admin 注册。

Board 模型注册到 custom_site (dashboard)，使用 DashboardAdminMixin 权限控制。
"""

from django.contrib import admin

from PowerAdapterBlogs.base_admin import DashboardAdminMixin
from PowerAdapterBlogs.cus_site import custom_site
from boards.models import Board


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
    list_editable = ['sort_order', 'is_active']
    list_filter = ['is_active', 'category']
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
