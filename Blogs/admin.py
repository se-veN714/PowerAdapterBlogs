from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.urls import reverse
from django.utils.html import format_html

from PowerAdapterBlogs.base_admin import BaseOwnerAdmin, DashboardAdminMixin
from PowerAdapterBlogs.cus_site import custom_site
from Blogs.adminforms import PostAdminForm
from Blogs.models import Post, Category, Tag, PostRevision

# Register your models here.
admin.site.register(Post)
admin.site.register(Category)
admin.site.register(Tag)
admin.site.register(LogEntry)


class PostInline(admin.TabularInline):  # 可选择继承自 admin.StackedInline 以获得不同的展示风格
    fields = ('title', 'desc')
    extra = 1
    model = Post


class PostRevisionInline(admin.TabularInline):
    model = PostRevision
    fields = ('version', 'change_type', 'edit_summary', 'editor', 'created_at')
    readonly_fields = ('version', 'change_type', 'edit_summary', 'editor', 'created_at')
    extra = 0
    can_delete = False
    verbose_name = "修订历史"
    verbose_name_plural = "修订历史"

    def has_add_permission(self, request, obj=None):
        return False  # 快照由系统自动创建，禁止手动添加


@admin.register(Category, site=custom_site)
class CategoryAdmin(DashboardAdminMixin, BaseOwnerAdmin):
    inlines = (PostInline,)
    list_display = ('name', 'status', 'is_nav', 'created_time', 'owner')
    field = ('name', 'status', 'is_nav')

    def post_count(self, obj):
        return obj.post_set.count()

    post_count.short_description = "文章数量"


@admin.register(Tag, site=custom_site)
class TagAdmin(DashboardAdminMixin, BaseOwnerAdmin):
    list_display = ('name', 'status', 'created_time')
    field = ('name', 'status')


class CategoryOwnerFilter(admin.SimpleListFilter):
    """
    自定义过滤去只展示当前用户分类
    """
    title = "分类过滤器"
    parameter_name = "owner_category"

    def lookups(self, request, queryset):
        return Category.objects.filter(owner=request.user).values_list("id", 'name', flat=True)

    def queryset(self, request, queryset):
        category_id = self.value()
        if category_id:
            return queryset.filter(category_id=category_id)
        return queryset


@admin.register(Post, site=custom_site)
class PostAdmin(DashboardAdminMixin, BaseOwnerAdmin):
    form = PostAdminForm
    inlines = [PostRevisionInline]
    list_display = [
        'title', 'category', 'status', 'visibility',
        'created_time', 'owner'
    ]
    list_display_links = []

    list_filter = ['category', 'visibility']
    search_fields = ['title', 'category__name']

    actions_on_top = True
    actions_on_bottom = True

    # 编辑页面
    save_on_top = True

    exclude = ['owner']
    fieldsets = (
        ('基础配置', {
            'fields': (
                ('title', 'category'),
                'status',
                'desc',
            )
        }),
        ('内容', {
            'fields': (
                'content',
            ),
        }),
        ('额外信息', {
            'fields': ('tag', 'visibility'),
        })
    )

    def operator(self, obj):
        return format_html(
            '<a href="{}">{编辑}</a>',
            reverse('cus_admin:blog_post_change', args=(obj.id,))
        )

    operator.short_description = "操作"

    class Meta:
        css = {
            'all': (
                'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
            )
        }

        js = (
            'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.min.js',
        )

@admin.register(LogEntry,site=custom_site)
class LogEntryAdmin(DashboardAdminMixin, admin.ModelAdmin):
    list_display = ('action_time', 'object_repr', 'object_id', 'action_flag', 'user', 'change_message')

    # DashboardAdminMixin 已提供 has_module_permission/has_view_permission 基于 is_dashboard_user
    # 这里只收紧 change/delete 到 superuser

    def has_change_permission(self, request, obj=None):
        """仅超级管理员可修改日志"""
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        """仅超级管理员可删除日志"""
        return request.user.is_superuser

