from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.generic import TemplateView

from Blogs.models import Post
from comment.form import CommentForm
from security.models import CommentEventLog


# Create your views here.
class CommentView(LoginRequiredMixin, TemplateView):
    """
    Handles user comment submissions on blog posts.

    This view requires the user to be authenticated before posting a comment.
    It also records a security event log that includes metadata such as IP,
    User-Agent, referrer, and a SM3-based client fingerprint.

    Methods:
        post(request, *args, **kwargs): Handles the comment form submission.
    """
    http_method_names = ['post']
    login_url = '/accounts/login/'  # 可自定义登录页
    redirect_field_name = None  # 禁止302跳转，用于API兼容（返回JSON）

    def handle_no_permission(self):
        """Override to return JSON instead of redirecting."""
        return JsonResponse({
            'success': False,
            'message': '请先登录后再发表评论。',
        }, status=401)

    def post(self, request, *args, **kwargs):
        post_slug = kwargs.get('slug')
        post = get_object_or_404(Post, slug=post_slug)

        form = CommentForm(request.POST)
        if not form.is_valid():
            errors = {field: [error for error in error_list]
                      for field, error_list in form.errors.items()}
            return JsonResponse({
                'success': False,
                'message': '请修正以下错误',
                'errors': errors
            }, status=400)

        instance = form.save(commit=False)
        instance.post = post
        instance.user = request.user  # 记录评论者
        instance.save()

        # --- 安全日志记录 ---
        snapshot = {
            "id": instance.id,
            "post_id": instance.post_id,
            "parent": instance.parent_id,
            "content": instance.content,
            "nickname": instance.nickname,
            "status": instance.status,
            "created_time": instance.created_time.isoformat(),
        }

        CommentEventLog.objects.create(
            comment=instance,
            action=CommentEventLog.UserAction.CREATE,
            action_at=timezone.now(),
            ip_address=getattr(request, "client_ip", None),
            user_agent=getattr(request, "client_ua", ""),
            referrer=getattr(request, "client_referrer", ""),
            url_path=getattr(request, "client_path", ""),
            client_fingerprint=getattr(request, "client_fp", ""),
            comment_snapshot=snapshot,
        )

        return JsonResponse({
            'success': True,
            'html': render_to_string('comment/item.html', {'comment': instance}),
            'message': '评论提交成功!',
        })
