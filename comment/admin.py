from django.contrib import admin
from .models import Comment


# Register your models here.
@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['content_short_description', 'post','nickname', 'created_time']

    def content_short_description(self, obj):
        """
        # 该方法用于对 admin 中 content 显示内容作限长
        :return: 限长检查后的 content
        """
        max_length = 50
        return obj.content[:max_length] + '...' if len(obj.content) > max_length else obj.content

    content_short_description.short_description = '评论内容'
