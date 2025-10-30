from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View

from comment.models import Comment
from security.services import moderate_comment


# Create your views here.
class CommentModerationView(LoginRequiredMixin, UserPassesTestMixin, View):
    """
    Allows admin or moderator users to change the status of a comment.

    This view records moderation actions using `moderate_comment()`
    to maintain full audit logs with IP, User-Agent, fingerprint, etc.
    """
    http_method_names = ['post']

    def test_func(self):
        """Only allow staff or superuser to moderate comments."""
        return self.request.user.is_staff or self.request.user.is_superuser

    def handle_no_permission(self):
        """Return JSON instead of redirecting."""
        return JsonResponse({
            'success': False,
            'message': '您没有权限执行此操作。',
        }, status=403)

    def post(self, request, *args, **kwargs):
        comment_id = request.POST.get("id")
        new_status = request.POST.get("status")
        reason = request.POST.get("reason", "")

        comment = get_object_or_404(Comment, id=comment_id)

        #  用 moderate_comment
        moderate_comment(
            comment=comment,
            new_status=new_status,
            request=request,
            reason=reason or "人工审核"
        )

        return JsonResponse({
            "success": True,
            "message": "评论状态已更新。",
            "data": {
                "id": comment.id,
                "new_status": comment.status,
                "timestamp": timezone.now().isoformat()
            }
        })
