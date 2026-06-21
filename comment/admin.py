import logging

from django.contrib import admin
from .models import Comment

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
            comment.status = Comment.Status.PUBLISHED
            comment.save(update_fields=['status'])
            logger.info(f"Comment 审核通过: comment_id={comment.id} "
                        f"old_status={old_status} user={request.user.id}")
        self.message_user(request, f"已通过 {queryset.count()} 条评论")
    approve_comments.short_description = "通过选中的评论"

    def reject_comments(self, request, queryset):
        for comment in queryset:
            old_status = comment.status
            comment.status = Comment.Status.REJECTED
            comment.save(update_fields=['status'])
            logger.info(f"Comment 审核拒绝: comment_id={comment.id} "
                        f"old_status={old_status} user={request.user.id}")
        self.message_user(request, f"已拒绝 {queryset.count()} 条评论")
    reject_comments.short_description = "拒绝选中的评论"

    def mark_spam(self, request, queryset):
        for comment in queryset:
            old_status = comment.status
            comment.status = Comment.Status.DELETED
            comment.save(update_fields=['status'])
            logger.info(f"Comment 标记垃圾: comment_id={comment.id} "
                        f"old_status={old_status} user={request.user.id}")
        self.message_user(request, f"已标记 {queryset.count()} 条评论为垃圾")
    mark_spam.short_description = "标记为垃圾"
