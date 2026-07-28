"""Boards 应用的视图和上下文处理器。

将活跃的首页板块数据注入所有模板上下文，供 base.html / index.html 使用。
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import FormView, ListView, TemplateView

from PowerAdapterBlogs.base_admin import has_dashboard_access
from accounts.services import (
    EMAIL_PURPOSE_BOARD_ACCESS,
    clear_email_verification,
    email_verification_is_verified,
    email_verification_remaining_seconds,
)
from boards.board_index import ASSEMBLERS, BOARD_TEMPLATES, prepare_skate_clips
from boards.forms import BoardAccessRequestForm
from boards.models import Board, BoardAccessRequest, SkateClip, SkateHomie
from boards.policies import (
    can_access_post_admin,
    can_create_post_in_any_board,
)
from boards.services import submit_board_access_request


class BoardAccessRequestView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    FormView,
):
    """Let verified users submit and inspect their own Board access requests."""

    template_name = "pages/boards/access_requests.html"
    form_class = BoardAccessRequestForm
    permission_required = "boards.apply_board_access"
    raise_exception = True
    success_url = reverse_lazy("boards:access-requests")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["access_requests"] = BoardAccessRequest.objects.filter(
            applicant=self.request.user
        ).select_related("board", "reviewed_by")
        context["show_submission_dialog"] = self.request.session.pop(
            "board_access_request_submitted",
            False,
        )
        context["email_verified"] = email_verification_is_verified(
            self.request,
            EMAIL_PURPOSE_BOARD_ACCESS,
        )
        context["email_verification_remaining"] = (
            email_verification_remaining_seconds(
                self.request,
                EMAIL_PURPOSE_BOARD_ACCESS,
            )
        )
        context["email_verification_url"] = reverse(
            "accounts:board-access-email-verify"
        )
        return context

    def form_valid(self, form):
        if not email_verification_is_verified(
            self.request,
            EMAIL_PURPOSE_BOARD_ACCESS,
        ):
            messages.info(self.request, "提交板块申请前，请先完成账号邮箱验证。")
            return redirect("accounts:board-access-email-verify")
        try:
            submit_board_access_request(
                applicant=self.request.user,
                board=form.cleaned_data["board"],
                requested_role=form.cleaned_data["requested_role"],
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        clear_email_verification(self.request, EMAIL_PURPOSE_BOARD_ACCESS)
        self.request.session["board_access_request_submitted"] = True
        messages.success(self.request, "板块权限申请已提交。")
        return super().form_valid(form)


class BoardIndexView(TemplateView):
    """GET /boards/<slug:slug>/ — 按 Board.slug 分派三板索引内容与模板。

    替换原 3 个 PreviewView（开发预览用静态视觉）。分派完全基于 Board.slug，
    不引入 board_type 字段（决策 2）；内容模板由 BOARD_TEMPLATES 给出。
    未知 slug 或已下线的板块统一返回 404。
    """

    def get(self, request, *args, **kwargs):
        slug = kwargs["slug"]
        if slug not in BOARD_TEMPLATES:
            raise Http404("Unknown board index slug")
        board = get_object_or_404(
            Board.objects.filter(slug__in=BOARD_TEMPLATES),
            slug=slug,
            is_active=True,
        )
        self.board = board
        self.template_name = BOARD_TEMPLATES[slug]
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["board"] = self.board
        context.update(ASSEMBLERS[self.board.slug](self.board))
        return context


class HomieLineView(TemplateView):
    """htmx 端点：GET /boards/<slug>/homie/<node_index>/ 返回 Selected Line 片段。

    仅渲染单个 Homie 的 _selected_line.html 片段（其公开 Clip 列表）。
    无权限查询、不鉴权——内容仅展示，授权由 Admin 写权限（superuser）保证。
    """

    template_name = "pages/boards/skateboard/_selected_line.html"

    def get(self, request, *args, **kwargs):
        board = get_object_or_404(Board, slug=kwargs["slug"], is_active=True)
        homie = get_object_or_404(
            SkateHomie, board=board, node_index=kwargs["node_index"]
        )
        self.selected_homie = homie
        self.clip_list = list(
            SkateClip.objects.filter(homie=homie, is_public=True).order_by(
                "order", "pk"
            )
        )
        self.clip_groups = prepare_skate_clips(self.clip_list)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["selected_homie"] = self.selected_homie
        context["clip_list"] = self.clip_list
        context["clip_groups"] = self.clip_groups
        return context


class SkateClipListView(ListView):
    """Public chronological archive of published skateboard clips."""

    template_name = "pages/boards/skateboard/clip_list.html"
    context_object_name = "clips"
    paginate_by = 12

    def get_queryset(self):
        self.board = get_object_or_404(Board, slug="skateboard", is_active=True)
        return (
            SkateClip.objects.filter(homie__board=self.board, is_public=True)
            .select_related("homie")
            .order_by(F("filmed_at").desc(nulls_last=True), "-created_at", "-pk")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["board"] = self.board
        prepare_skate_clips(context["clips"])
        return context


def boards_context(request):
    """上下文处理器：注入活跃的首页板块列表。

    按 sort_order 排序，仅供首页 editorial-section 遍历渲染。
    返回 board 对象，模板可通过 board.glitch_color 等属性使用。
    """
    boards = (
        Board.objects.filter(is_active=True, slug__in=BOARD_TEMPLATES)
        .select_related("category")
        .order_by("sort_order")
    )
    from moderation.policies import can_access_moderation_center

    return {
        "boards": boards,
        "can_create_board_post": can_create_post_in_any_board(request.user),
        "can_access_review_workspace": can_access_post_admin(request.user),
        "can_access_dashboard": has_dashboard_access(request.user),
        "can_access_moderation_center": can_access_moderation_center(request.user),
    }
