from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import ListView, TemplateView

from accounts.services import set_account_active_state
from boards.models import BoardAccessRequest, BoardMembership
from boards.policies import (
    can_access_board_admin,
    can_access_comment_admin,
    can_moderate_comment,
    comments_visible_to_moderator,
)
from boards.services import decide_board_access_request
from comment.models import Comment
from security.services import moderate_comment

from .policies import (
    can_access_moderation_center,
    can_review_accounts,
    moderation_capabilities,
)


class ModerationAccessMixin(LoginRequiredMixin):
    permission_check = staticmethod(can_access_moderation_center)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not self.permission_check(request.user):
            raise PermissionDenied("当前账号没有对应的审核权限。")
        return super().dispatch(request, *args, **kwargs)


class ModerationHubView(ModerationAccessMixin, TemplateView):
    template_name = "pages/moderation/hub.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["capabilities"] = moderation_capabilities(self.request.user)
        if context["capabilities"]["accounts"]:
            context["pending_accounts"] = get_user_model().objects.filter(
                is_superuser=False,
                is_active=False,
                account_invitation__accepted_at__isnull=True,
            ).count()
        if context["capabilities"]["comments"]:
            context["pending_comments"] = comments_visible_to_moderator(
                self.request.user,
                Comment.objects.filter(status=Comment.Status.PENDING),
            ).count()
        if context["capabilities"]["boards"]:
            context["pending_board_requests"] = self._board_requests().count()
        return context

    def _board_requests(self):
        queryset = BoardAccessRequest.objects.filter(
            status=BoardAccessRequest.Status.PENDING
        )
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(
            board__memberships__user=self.request.user,
            board__memberships__role=BoardMembership.Role.MANAGER,
            board__memberships__is_active=True,
            board__is_active=True,
        ).distinct()


class AccountModerationView(ModerationAccessMixin, ListView):
    template_name = "pages/moderation/accounts.html"
    context_object_name = "accounts"
    paginate_by = 20
    permission_check = staticmethod(can_review_accounts)

    def get_queryset(self):
        queryset = (
            get_user_model().objects.filter(
                is_superuser=False,
                is_dashboard_user=False,
                is_staff=False,
            )
            .select_related("account_invitation")
            .order_by("-date_joined", "pk")
        )
        query = self.request.GET.get("q", "").strip()[:80]
        state = self.request.GET.get("state", "").strip()
        if query:
            queryset = queryset.filter(
                Q(username__icontains=query) | Q(email__icontains=query)
            )
        if state == "active":
            queryset = queryset.filter(is_active=True)
        elif state == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset

    def post(self, request, *args, **kwargs):
        target = get_object_or_404(get_user_model(), pk=request.POST.get("user_id"))
        action = request.POST.get("action")
        if action not in {"activate", "deactivate"}:
            raise ValidationError("未知的账号审核动作。")
        try:
            set_account_active_state(
                actor=request.user,
                target=target,
                is_active=action == "activate",
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                f"账号 {target.username} 已{'启用' if action == 'activate' else '停用'}。",
            )
        return redirect("moderation:accounts")


class CommentModerationView(ModerationAccessMixin, ListView):
    template_name = "pages/moderation/comments.html"
    context_object_name = "comments"
    paginate_by = 20
    permission_check = staticmethod(can_access_comment_admin)

    def get_queryset(self):
        queryset = Comment.objects.select_related(
            "post", "post__category", "user", "user__profile"
        )
        queryset = comments_visible_to_moderator(self.request.user, queryset)
        raw_status = self.request.GET.get("status", str(Comment.Status.PENDING))
        allowed = {str(value) for value, _label in Comment.Status.choices}
        if raw_status in allowed:
            queryset = queryset.filter(status=int(raw_status))
        query = self.request.GET.get("q", "").strip()[:100]
        if query:
            queryset = queryset.filter(
                Q(content__icontains=query)
                | Q(post__title__icontains=query)
                | Q(user__username__icontains=query)
            )
        return queryset.order_by("-created_time", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Comment.Status.choices
        context["selected_status"] = self.request.GET.get(
            "status", str(Comment.Status.PENDING)
        )
        return context

    def post(self, request, *args, **kwargs):
        comment = get_object_or_404(
            Comment.objects.select_related("post"),
            pk=request.POST.get("comment_id"),
        )
        if not can_moderate_comment(request.user, comment):
            raise PermissionDenied("无权审核该板块的评论。")
        transitions = {
            "approve": (Comment.Status.PUBLISHED, "审核中心：通过评论"),
            "reject": (Comment.Status.REJECTED, "审核中心：驳回评论"),
            "delete": (Comment.Status.DELETED, "审核中心：删除评论"),
        }
        transition = transitions.get(request.POST.get("action"))
        if transition is None:
            raise ValidationError("未知的评论审核动作。")
        moderate_comment(
            comment=comment,
            new_status=transition[0],
            request=request,
            reason=transition[1],
        )
        messages.success(request, "评论状态已更新。")
        return redirect("moderation:comments")


class BoardAccessModerationView(ModerationAccessMixin, ListView):
    template_name = "pages/moderation/boards.html"
    context_object_name = "access_requests"
    paginate_by = 20
    permission_check = staticmethod(can_access_board_admin)

    def get_queryset(self):
        queryset = BoardAccessRequest.objects.select_related(
            "board", "applicant", "reviewed_by"
        )
        if not self.request.user.is_superuser:
            queryset = queryset.filter(
                board__is_active=True,
                board__memberships__user=self.request.user,
                board__memberships__role=BoardMembership.Role.MANAGER,
                board__memberships__is_active=True,
            ).distinct()
        status = self.request.GET.get("status", BoardAccessRequest.Status.PENDING)
        if status in {value for value, _label in BoardAccessRequest.Status.choices}:
            queryset = queryset.filter(status=status)
        return queryset.order_by("-created_at", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = BoardAccessRequest.Status.choices
        context["selected_status"] = self.request.GET.get(
            "status", BoardAccessRequest.Status.PENDING
        )
        return context

    def post(self, request, *args, **kwargs):
        access_request = get_object_or_404(
            BoardAccessRequest.objects.select_related("board", "applicant"),
            pk=request.POST.get("request_id"),
        )
        action = request.POST.get("action")
        if action not in {"approve", "reject"}:
            raise ValidationError("未知的板块权限审核动作。")
        try:
            decide_board_access_request(
                access_request=access_request,
                actor=request.user,
                approve=action == "approve",
                note=request.POST.get("note", "")[:500],
            )
        except (PermissionDenied, ValidationError) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            messages.error(request, detail)
        else:
            messages.success(request, "板块权限申请已处理。")
        return redirect("moderation:boards")
