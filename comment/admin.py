import logging

from django.contrib import admin, messages

from PowerAdapterBlogs.base_admin import DashboardAdminMixin
from PowerAdapterBlogs.cus_site import custom_site
from boards.policies import (
    can_access_comment_admin,
    can_moderate_comment,
    comments_visible_to_moderator,
)
from .models import Comment
from security.services import moderate_comment

logger = logging.getLogger(__name__)


# Register your models here.
@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['content_short_description', 'post','nickname', 'created_time']
    actions = ['approve_comments', 'reject_comments', 'mark_spam']

    def content_short_description(self, obj):
        """
        # 该方法用于对 admin 中 content 显示内容作限长
        :return: 限长检查后的 content
        """
        max_length = 50
        return obj.content[:max_length] + '...' if len(obj.content) > max_length else obj.content

    content_short_description.short_description = '评论内容'

    def approve_comments(self, request, queryset):
        for comment in queryset:
            old_status = comment.status
            moderate_comment(
                comment=comment,
                new_status=Comment.Status.PUBLISHED,
                request=request,
                reason='Admin 批量审核通过',
            )
            logger.info(f"Comment 审核通过: comment_id={comment.id} "
                        f"old_status={old_status} user={request.user.id}")
        self.message_user(request, f"已通过 {queryset.count()} 条评论")
    approve_comments.short_description = "通过选中的评论"

    def reject_comments(self, request, queryset):
        for comment in queryset:
            old_status = comment.status
            moderate_comment(
                comment=comment,
                new_status=Comment.Status.REJECTED,
                request=request,
                reason='Admin 批量审核拒绝',
            )
            logger.info(f"Comment 审核拒绝: comment_id={comment.id} "
                        f"old_status={old_status} user={request.user.id}")
        self.message_user(request, f"已拒绝 {queryset.count()} 条评论")
    reject_comments.short_description = "拒绝选中的评论"

    def mark_spam(self, request, queryset):
        for comment in queryset:
            old_status = comment.status
            moderate_comment(
                comment=comment,
                new_status=Comment.Status.DELETED,
                request=request,
                reason='Admin 标记为垃圾',
            )
            logger.info(f"Comment 标记垃圾: comment_id={comment.id} "
                        f"old_status={old_status} user={request.user.id}")
        self.message_user(request, f"已标记 {queryset.count()} 条评论为垃圾")
    mark_spam.short_description = "标记为垃圾"


@admin.register(Comment, site=custom_site)
class BoardScopedCommentAdmin(DashboardAdminMixin, admin.ModelAdmin):
    """Board-scoped, read-only moderation queue for Stage 4."""

    list_display = [
        "content_short_description",
        "post",
        "nickname",
        "status",
        "created_time",
    ]
    list_display_links = ["content_short_description"]
    list_filter = ["status", "created_time"]
    search_fields = ["content", "nickname", "post__title"]
    list_select_related = ["post", "post__category", "user"]
    actions = ["approve_comments", "reject_comments", "mark_spam"]

    @admin.display(description="评论内容")
    def content_short_description(self, obj):
        max_length = 50
        if len(obj.content) <= max_length:
            return obj.content
        return f"{obj.content[:max_length]}..."

    def has_module_permission(self, request):
        return can_access_comment_admin(request.user)

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return can_access_comment_admin(request.user)
        return can_moderate_comment(request.user, obj)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return comments_visible_to_moderator(request.user, queryset)

    def _moderate_queryset(self, request, queryset, *, new_status, reason):
        succeeded = 0
        rejected = 0
        for comment in queryset.select_related("post", "post__category"):
            if not can_moderate_comment(request.user, comment):
                rejected += 1
                continue
            moderate_comment(
                comment=comment,
                new_status=new_status,
                request=request,
                reason=reason,
            )
            succeeded += 1

        if succeeded:
            self.message_user(request, f"已处理 {succeeded} 条评论", messages.SUCCESS)
        if rejected:
            self.message_user(
                request,
                f"跳过 {rejected} 条非所属板块评论",
                messages.WARNING,
            )

    @admin.action(description="通过选中的评论", permissions=["view"])
    def approve_comments(self, request, queryset):
        self._moderate_queryset(
            request,
            queryset,
            new_status=Comment.Status.PUBLISHED,
            reason="Dashboard Board 审核通过",
        )

    @admin.action(description="拒绝选中的评论", permissions=["view"])
    def reject_comments(self, request, queryset):
        self._moderate_queryset(
            request,
            queryset,
            new_status=Comment.Status.REJECTED,
            reason="Dashboard Board 审核拒绝",
        )

    @admin.action(description="标记为垃圾", permissions=["view"])
    def mark_spam(self, request, queryset):
        self._moderate_queryset(
            request,
            queryset,
            new_status=Comment.Status.DELETED,
            reason="Dashboard Board 标记为垃圾",
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
