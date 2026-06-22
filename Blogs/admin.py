from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry
from django.urls import reverse
from django.utils.html import format_html

from PowerAdapterBlogs.base_admin import BaseOwnerAdmin, DashboardAdminMixin
from PowerAdapterBlogs.cus_site import custom_site
from Blogs.adminforms import PostAdminForm
from Blogs.management.commands.rewrap_posts import apply_word_wrap_to_queryset
from Blogs.revisions import create_revision
from Blogs.models import Post, Category, Tag, PostRevision

# Register your models here.
admin.site.register(Post)
admin.site.register(Category)
admin.site.register(Tag)
admin.site.register(LogEntry)
admin.site.register(PostRevision)


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

    def has_add_permission(self, request):
        return request.user.has_perm('Blogs.manage_category')

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm('Blogs.manage_category')

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm('Blogs.manage_category')


@admin.register(Tag, site=custom_site)
class TagAdmin(DashboardAdminMixin, BaseOwnerAdmin):
    list_display = ('name', 'status', 'created_time')
    field = ('name', 'status')

    def has_add_permission(self, request):
        return request.user.has_perm('Blogs.manage_tag')

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm('Blogs.manage_tag')

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm('Blogs.manage_tag')


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


def rewrap_content_action(modeladmin, request, queryset):
    """Admin action: 对选中文章内容执行单词边界分行。

    调用 _word_wrap() 对 Post.content 做 80 字换行预处理，
    提升后续修订 diff 的颗粒度。变更后自动创建修订快照。
    """
    result = apply_word_wrap_to_queryset(queryset, editor=request.user)
    if result['success']:
        messages.success(
            request,
            f"分行完成: 成功 {result['success']} 篇 / "
            f"跳过 {result['skipped']} 篇 (无需分行)"
            f"{'（已自动创建修订快照）' if result['success'] else ''}",
        )
    if result['failed']:
        messages.error(request, f"分行失败: {result['failed']} 篇")
    if result['success'] == 0 and result['failed'] == 0:
        messages.info(request, "选中的文章均无需分行")


rewrap_content_action.short_description = "📝 对选中文章内容执行单词边界分行"


def _is_reviewer(user) -> bool:
    """审核者：有 is_reviewer 标志的 dashboard 用户"""
    return user.is_authenticated and user.is_reviewer


def _is_editor(user) -> bool:
    """编辑者：dashboard 用户但非审核者"""
    return user.is_authenticated and user.is_dashboard_user and not user.is_reviewer


# ===== Review Workflow Actions =====

def submit_for_review_action(modeladmin, request, queryset):
    """编辑者：提交文章进入审核队列"""
    updated = queryset.filter(status=Post.STATUS_DRAFT).update(
        status=Post.STATUS_REVIEW
    )
    if updated:
        messages.success(request, f"已提交 {updated} 篇文章进入审核队列")
    else:
        messages.warning(request, "选中的文章中没有草稿状态的文章")


submit_for_review_action.short_description = "📤 提交审核"


def approve_review_action(modeladmin, request, queryset):
    """审核者：通过审核 → 发布文章"""
    updated = queryset.filter(status=Post.STATUS_REVIEW).update(
        status=Post.STATUS_NORMAL
    )
    if updated:
        # 为每篇通过审核的文章创建修订快照
        for post in queryset.filter(status=Post.STATUS_NORMAL):
            if post.id in list(queryset.filter(status=Post.STATUS_REVIEW)
                               .values_list('id', flat=True)):
                continue
        posts = Post.objects.filter(
            id__in=list(queryset.values_list('id', flat=True))
        ).filter(status=Post.STATUS_NORMAL)
        for post in posts:
            create_revision(post, request.user, change_type='minor',
                           edit_summary='审核通过 → 已发布')
        messages.success(request, f"已通过审核 {updated} 篇文章（已发布）")
    else:
        messages.warning(request, "选中的文章中没有待审核状态的文章")


approve_review_action.short_description = "✅ 通过审核（发布）"


def reject_review_action(modeladmin, request, queryset):
    """审核者：驳回 → 退回草稿"""
    updated = queryset.filter(status=Post.STATUS_REVIEW).update(
        status=Post.STATUS_DRAFT
    )
    if updated:
        messages.success(request, f"已驳回 {updated} 篇文章（退回草稿）")
    else:
        messages.warning(request, "选中的文章中没有待审核状态的文章")


reject_review_action.short_description = "❌ 驳回（退回草稿）"


def unpublish_action(modeladmin, request, queryset):
    """审核者：下架已发布文章"""
    updated = queryset.filter(status=Post.STATUS_NORMAL).update(
        status=Post.STATUS_DELETE
    )
    if updated:
        messages.success(request, f"已下架 {updated} 篇文章")
    else:
        messages.warning(request, "选中的文章中没有已发布状态的文章")


unpublish_action.short_description = "📥 下架"


# ===== PostAdmin =====

@admin.register(Post, site=custom_site)
class PostAdmin(DashboardAdminMixin, BaseOwnerAdmin):
    form = PostAdminForm
    inlines = [PostRevisionInline]
    list_display = [
        'title', 'category', 'status_display', 'visibility',
        'created_time', 'owner'
    ]
    list_display_links = []

    list_filter = ['status', 'category', 'visibility']
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

    # ===== 动态 actions：按角色显示不同操作 =====

    def get_actions(self, request):
        actions = super().get_actions(request)

        if request.user.is_superuser:
            # superuser 有所有操作
            actions['rewrap_content_action'] = (
                rewrap_content_action, 'rewrap_content_action',
                rewrap_content_action.short_description
            )
            actions['submit_for_review_action'] = (
                submit_for_review_action, 'submit_for_review_action',
                submit_for_review_action.short_description
            )
            actions['approve_review_action'] = (
                approve_review_action, 'approve_review_action',
                approve_review_action.short_description
            )
            actions['reject_review_action'] = (
                reject_review_action, 'reject_review_action',
                reject_review_action.short_description
            )
            actions['unpublish_action'] = (
                unpublish_action, 'unpublish_action',
                unpublish_action.short_description
            )
        elif _is_reviewer(request.user):
            actions['approve_review_action'] = (
                approve_review_action, 'approve_review_action',
                approve_review_action.short_description
            )
            actions['reject_review_action'] = (
                reject_review_action, 'reject_review_action',
                reject_review_action.short_description
            )
            actions['unpublish_action'] = (
                unpublish_action, 'unpublish_action',
                unpublish_action.short_description
            )
        elif _is_editor(request.user):
            actions['submit_for_review_action'] = (
                submit_for_review_action, 'submit_for_review_action',
                submit_for_review_action.short_description
            )

        return actions

    # ===== 权限颗粒化 =====

    def has_add_permission(self, request):
        """编辑者和审核者均可新建文章"""
        return request.user.is_dashboard_user

    def has_change_permission(self, request, obj=None):
        """
        编辑者 → 可编辑自己的文章
        审核者 → 可编辑所有文章（变更 status 来审核）
        """
        if not request.user.is_dashboard_user:
            return False
        if _is_reviewer(request.user):
            return True  # 审核者可编辑所有
        if obj is not None:
            return obj.owner == request.user  # 编辑者只能改自己的
        return True  # 列表页允许进入

    def has_delete_permission(self, request, obj=None):
        """仅 superuser 可删除"""
        return request.user.is_superuser

    def get_queryset(self, request):
        """按角色过滤可见文章"""
        qs = super().get_queryset(request)
        if request.user.is_superuser or _is_reviewer(request.user):
            return qs  # 审核者看全部
        # 编辑者只看自己的
        return qs.filter(owner=request.user)

    def get_readonly_fields(self, request, obj=None):
        """
        编辑者：status 字段只可设为 DRAFT/REVIEW，不可直接发布
        审核者：全部字段可编辑
        """
        readonly = list(super().get_readonly_fields(request, obj) or [])
        if _is_editor(request.user):
            readonly.append('status')  # 编辑者通过 action 提交审核，不可直接改状态
        return readonly

    @admin.display(description='状态')
    def status_display(self, obj):
        status_map = {
            Post.STATUS_DRAFT: '📝 草稿',
            Post.STATUS_REVIEW: '⏳ 审核中',
            Post.STATUS_NORMAL: '✅ 已发布',
            Post.STATUS_DELETE: '🗑 已删除',
        }
        return status_map.get(obj.status, f'未知({obj.status})')

    def operator(self, obj):
        return format_html(
            '<a href="{}">{编辑}</a>',
            reverse('cus_admin:blog_post_change', args=(obj.id,))
        )

    operator.short_description = "操作"

    def save_model(self, request, obj, form, change):
        """保存文章时自动创建修订快照 + 审核状态流转。

        编辑者新建 → 默认 DRAFT，编辑已有 → 保持原状态或回退到 DRAFT
        审核者编辑 → 可自由设置状态
        """
        is_new = not change
        old_status = None

        if not is_new:
            try:
                old_status = Post.objects.only('status').get(pk=obj.pk).status
            except Post.DoesNotExist:
                pass

        # 编辑者强制状态流转规则
        if _is_editor(request.user):
            if is_new:
                obj.status = Post.STATUS_DRAFT  # 新建文章强制草稿
            elif old_status == Post.STATUS_NORMAL:
                # 编辑已发布文章 → 回退到草稿（需要重新审核）
                obj.status = Post.STATUS_DRAFT

        super().save_model(request, obj, form, change)  # 先保存 Post

        # 创建修订快照
        if is_new:
            create_revision(obj, request.user, change_type='major',
                           edit_summary='通过管理后台创建')
        else:
            summary = '通过管理后台编辑'
            if old_status == Post.STATUS_NORMAL and _is_editor(request.user):
                summary = '编辑已发布文章 → 退回草稿（需重新审核）'
            create_revision(obj, request.user, change_type='minor',
                           edit_summary=summary)

    class Meta:
        css = {
            'all': (
                'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
            )
        }

        js = (
            'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.min.js',
        )

@admin.register(PostRevision, site=custom_site)
class PostRevisionAdmin(DashboardAdminMixin, admin.ModelAdmin):
    """文章修订历史 — dashboard 可见，只读（系统自动创建，禁止手动增删改）"""
    list_display = [
        'post_title', 'version', 'change_type', 'edit_summary',
        'editor', 'created_at',
    ]
    list_display_links = ['version']
    list_filter = ['change_type', 'created_at']
    search_fields = ['post__title', 'edit_summary']
    readonly_fields = [
        'post', 'major', 'minor', 'version',
        'title', 'desc', 'content', 'slug',
        'editor', 'change_type', 'edit_summary',
        'diff_from_previous', 'created_at',
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']

    fieldsets = (
        ('文章信息', {'fields': (('post', 'version'), ('major', 'minor'))}),
        ('内容快照', {'fields': ('title', 'desc', 'content', 'slug')}),
        ('版本元信息', {
            'fields': (('editor', 'change_type'), 'edit_summary', 'created_at'),
        }),
        ('预计算 Diff', {
            'fields': ('diff_from_previous',),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='文章', ordering='post__title')
    def post_title(self, obj):
        return obj.post.title

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


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

