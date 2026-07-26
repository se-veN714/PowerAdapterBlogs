from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils.html import format_html

from PowerAdapterBlogs.base_admin import BaseOwnerAdmin, DashboardAdminMixin
from PowerAdapterBlogs.cus_site import custom_site
from Blogs.adminforms import PostAdminForm
from Blogs.management.commands.rewrap_posts import apply_word_wrap_to_queryset
from Blogs.revisions import create_revision
from Blogs.models import Post, Category, Tag, PostRevision, PostWorkflowEvent
from Blogs.services import (
    approve_post,
    record_post_workflow_event,
    reject_post,
    submit_post_for_review,
    unpublish_post,
)
from boards.policies import (
    board_for_post,
    can_access_post_admin,
    can_change_posts_in_admin,
    can_create_post,
    can_create_post_in_any_board,
    can_edit_post,
    can_review_posts_in_admin,
    can_view_post,
    can_view_post_revision,
    categories_available_to,
    categories_for_post_creation,
    post_revisions_visible_to,
    posts_visible_to,
)

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


class PostWorkflowEventInline(admin.TabularInline):
    model = PostWorkflowEvent
    fields = (
        "event_type",
        "from_status",
        "to_status",
        "revision",
        "actor",
        "note",
        "created_at",
    )
    readonly_fields = fields
    extra = 0
    can_delete = False
    verbose_name = "工作流事件"
    verbose_name_plural = "工作流事件"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Category, site=custom_site)
class CategoryAdmin(DashboardAdminMixin, BaseOwnerAdmin):
    inlines = (PostInline,)
    list_display = ('name', 'status', 'is_nav', 'created_time', 'owner')
    field = ('name', 'status', 'is_nav')

    def post_count(self, obj):
        return obj.post_set.count()

    post_count.short_description = "文章数量"

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


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


class BoardScopedCategoryFilter(admin.SimpleListFilter):
    """Only expose categories mapped to one of the user's active Boards."""

    title = "Board category"
    parameter_name = "board_category"

    def lookups(self, request, model_admin):
        categories = categories_available_to(request.user, Category.objects.all())
        return categories.order_by("name").values_list("pk", "name")

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(category_id=self.value())
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


# ===== Review Workflow Actions =====


def _run_post_workflow_action(*, request, queryset, service, success_label):
    succeeded = 0
    rejected = 0
    for post in queryset.select_related("category", "owner"):
        try:
            service(post=post, user=request.user)
        except (PermissionDenied, ValidationError):
            rejected += 1
        else:
            succeeded += 1

    if succeeded:
        messages.success(request, f"{success_label} {succeeded} 篇文章")
    if rejected:
        messages.warning(request, f"跳过 {rejected} 篇无权限或状态不匹配的文章")

def submit_for_review_action(modeladmin, request, queryset):
    """编辑者：提交文章进入审核队列"""
    _run_post_workflow_action(
        request=request,
        queryset=queryset,
        service=submit_post_for_review,
        success_label="已提交审核",
    )


submit_for_review_action.short_description = "📤 提交审核"


def approve_review_action(modeladmin, request, queryset):
    """审核者：通过审核 → 发布文章"""
    _run_post_workflow_action(
        request=request,
        queryset=queryset,
        service=approve_post,
        success_label="已通过审核并发布",
    )


approve_review_action.short_description = "✅ 通过审核（发布）"


def reject_review_action(modeladmin, request, queryset):
    """审核者：驳回 → 退回草稿"""
    _run_post_workflow_action(
        request=request,
        queryset=queryset,
        service=reject_post,
        success_label="已驳回",
    )


reject_review_action.short_description = "❌ 驳回（退回草稿）"


def unpublish_action(modeladmin, request, queryset):
    """审核者：下架已发布文章"""
    _run_post_workflow_action(
        request=request,
        queryset=queryset,
        service=unpublish_post,
        success_label="已下架",
    )


unpublish_action.short_description = "📥 下架"


# ===== PostAdmin =====

@admin.register(Post, site=custom_site)
class PostAdmin(DashboardAdminMixin, admin.ModelAdmin):
    form = PostAdminForm
    inlines = [PostRevisionInline, PostWorkflowEventInline]
    list_display = [
        'title', 'category', 'status_display', 'visibility',
        'created_time', 'owner'
    ]
    list_display_links = ['title']

    list_filter = ['status', BoardScopedCategoryFilter, 'visibility']
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
        else:
            if can_change_posts_in_admin(request.user):
                actions['submit_for_review_action'] = (
                    submit_for_review_action,
                    'submit_for_review_action',
                    submit_for_review_action.short_description,
                )
            if can_review_posts_in_admin(request.user):
                actions['approve_review_action'] = (
                    approve_review_action,
                    'approve_review_action',
                    approve_review_action.short_description,
                )
                actions['reject_review_action'] = (
                    reject_review_action,
                    'reject_review_action',
                    reject_review_action.short_description,
                )
                actions['unpublish_action'] = (
                    unpublish_action,
                    'unpublish_action',
                    unpublish_action.short_description,
                )
        return actions

    # ===== 权限颗粒化 =====

    def has_module_permission(self, request):
        return can_access_post_admin(request.user)

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return can_access_post_admin(request.user)
        return can_view_post(request.user, obj)

    def has_add_permission(self, request):
        return can_create_post_in_any_board(request.user)

    def has_change_permission(self, request, obj=None):
        """
        编辑者 → 可编辑自己的文章
        审核者 → 可编辑所有文章（变更 status 来审核）
        """
        if obj is None:
            return can_change_posts_in_admin(request.user)
        return can_edit_post(request.user, obj)

    def has_delete_permission(self, request, obj=None):
        """仅 superuser 可删除"""
        return request.user.is_superuser

    def get_queryset(self, request):
        """按角色过滤可见文章"""
        queryset = super().get_queryset(request)
        return posts_visible_to(request.user, queryset)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        category_field = form.base_fields.get("category")
        if category_field is not None:
            if obj is not None and not can_edit_post(request.user, obj):
                category_field.queryset = categories_available_to(
                    request.user,
                    Category.objects.all(),
                )
            else:
                category_field.queryset = categories_for_post_creation(
                    request.user,
                    Category.objects.all(),
                )
        return form

    def get_readonly_fields(self, request, obj=None):
        """
        编辑者：status 字段只可设为 DRAFT/REVIEW，不可直接发布
        审核者：全部字段可编辑
        """
        readonly = list(super().get_readonly_fields(request, obj) or [])
        if not request.user.is_superuser:
            readonly.append('status')
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
        old_owner_id = None
        old_snapshot = None

        if not is_new:
            try:
                previous = Post.objects.only(
                    'status',
                    'owner_id',
                    'title',
                    'desc',
                    'content',
                    'slug',
                ).get(pk=obj.pk)
                old_status = previous.status
                old_owner_id = previous.owner_id
                old_snapshot = (
                    previous.title,
                    previous.desc,
                    previous.content,
                    previous.slug,
                )
            except Post.DoesNotExist:
                pass

        if is_new:
            obj.owner = request.user
            if not can_create_post(request.user, board_for_post(obj)):
                raise PermissionDenied
            if not request.user.is_superuser:
                obj.status = Post.STATUS_DRAFT
        else:
            obj.owner_id = old_owner_id
            if not can_edit_post(request.user, obj):
                raise PermissionDenied
            if not request.user.is_superuser and old_status != Post.STATUS_DRAFT:
                obj.status = Post.STATUS_DRAFT

        super().save_model(request, obj, form, change)  # 先保存 Post

        revision = None
        new_snapshot = (obj.title, obj.desc, obj.content, obj.slug)
        snapshot_changed = is_new or old_snapshot != new_snapshot
        # 创建修订快照
        if is_new:
            revision = create_revision(
                obj,
                request.user,
                change_type='major',
                edit_summary='通过管理后台创建',
            )
        elif snapshot_changed:
            summary = '通过管理后台编辑'
            if old_status != Post.STATUS_DRAFT and not request.user.is_superuser:
                summary = '编辑已提交或发布文章 → 退回草稿（需重新审核）'
            revision = create_revision(
                obj,
                request.user,
                change_type='minor',
                edit_summary=summary,
            )
        else:
            revision = obj.revisions.order_by('-major', '-minor').first()

        if not is_new and old_status != obj.status:
            record_post_workflow_event(
                post=obj,
                actor=request.user,
                from_status=old_status,
                to_status=obj.status,
                revision=revision,
                note="通过管理后台编辑状态",
            )

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
        'diff_from_previous', 'diff_structured', 'diff_algorithm',
        'diff_stats', 'created_at',
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
            'fields': (
                'diff_algorithm', 'diff_stats', 'diff_structured',
                'diff_from_previous',
            ),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='文章', ordering='post__title')
    def post_title(self, obj):
        return obj.post.title

    def has_module_permission(self, request):
        return can_access_post_admin(request.user)

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return can_access_post_admin(request.user)
        return can_view_post_revision(request.user, obj)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return post_revisions_visible_to(request.user, queryset)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


@admin.register(PostWorkflowEvent, site=custom_site)
class PostWorkflowEventAdmin(DashboardAdminMixin, admin.ModelAdmin):
    """Board-scoped, read-only Post workflow history."""

    list_display = (
        "post",
        "event_type",
        "from_status",
        "to_status",
        "revision",
        "actor",
        "created_at",
    )
    list_filter = ("event_type", "from_status", "to_status", "created_at")
    search_fields = ("post__title", "actor__username", "note")
    readonly_fields = (
        "post",
        "event_type",
        "from_status",
        "to_status",
        "revision",
        "actor",
        "note",
        "created_at",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-pk")

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            "post",
            "revision",
            "actor",
        )
        visible_post_ids = posts_visible_to(
            request.user,
            Post.objects.all(),
        ).values("pk")
        return queryset.filter(post_id__in=visible_post_ids)

    def has_module_permission(self, request):
        return can_access_post_admin(request.user)

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return can_access_post_admin(request.user)
        return can_view_post(request.user, obj.post)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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

