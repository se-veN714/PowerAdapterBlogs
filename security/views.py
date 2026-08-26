import logging

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View

from comment.models import Comment
from security.queries import query_audit_events
from security.services import moderate_comment


logger = logging.getLogger(__name__)


class AuditEventListView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Read Mongo-authoritative evidence without an outbox fallback."""

    http_method_names = ["get"]

    def test_func(self):
        user = self.request.user
        return user.is_active and (
            user.is_superuser or user.has_perm("security.view_audit_log")
        )

    def handle_no_permission(self):
        return JsonResponse(
            {"success": False, "message": "您没有权限查看安全审计。"},
            status=403,
        )

    def get(self, request, *args, **kwargs):
        try:
            page = query_audit_events(
                event_type=request.GET.get("event_type"),
                actor_id=request.GET.get("actor_id"),
                target_type=request.GET.get("target_type"),
                target_id=request.GET.get("target_id"),
                partition=request.GET.get("partition"),
                cursor=request.GET.get("cursor"),
                limit=request.GET.get("limit", 50),
            )
        except ValueError:
            return JsonResponse(
                {"success": False, "message": "无效的审计查询参数。"},
                status=400,
            )
        except Exception as exc:
            logger.warning(
                "Mongo audit query unavailable error_code=%s",
                type(exc).__name__,
            )
            return JsonResponse(
                {
                    "success": False,
                    "message": "安全审计查询暂不可用。",
                    "authority": "mongodb",
                },
                status=503,
            )
        return JsonResponse(
            {
                "success": True,
                "authority": "mongodb",
                "results": list(page.items),
                "next_cursor": page.next_cursor,
                "limit": page.limit,
            }
        )


# Create your views here.
class CommentModerationView(LoginRequiredMixin, UserPassesTestMixin, View):
    """
    Allows admin or moderator users to change the status of a comment.

    This view records moderation through a minimized transactional outbox event.
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
        try:
            moderate_comment(
                comment=comment,
                new_status=new_status,
                request=request,
                reason=reason or "人工审核",
            )
        except (TypeError, ValueError):
            return JsonResponse(
                {"success": False, "message": "无效的评论状态。"},
                status=400,
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
