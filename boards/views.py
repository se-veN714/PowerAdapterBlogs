"""Boards 应用的视图和上下文处理器。

将活跃的首页板块数据注入所有模板上下文，供 base.html / index.html 使用。
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView

from PowerAdapterBlogs.base_admin import has_dashboard_access
from boards.forms import BoardAccessRequestForm
from boards.models import Board, BoardAccessRequest
from boards.policies import can_create_post_in_any_board
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
        return context

    def form_valid(self, form):
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
        messages.success(self.request, "板块权限申请已提交，审核结果会显示在本页。")
        return super().form_valid(form)


class SkateboardBoardPreviewView(TemplateView):
    """本地预览用：直接渲染 Skateboard Board Index 静态视觉（mock 数据分支）。

    仅作开发预览，便于在浏览器查看前端效果；生产路由由后端集成阶段在接入
    §6.12 契约（homies / selected_homie / clip_list / homie_line_url / open_node_url）
    后提供，届时此视图可移除。
    """

    template_name = "pages/boards/skateboard/index.html"


def boards_context(request):
    """上下文处理器：注入活跃的首页板块列表。

    按 sort_order 排序，仅供首页 editorial-section 遍历渲染。
    返回 board 对象，模板可通过 board.glitch_color 等属性使用。
    """
    boards = (
        Board.objects.filter(is_active=True)
        .select_related("category")
        .order_by("sort_order")
    )
    return {
        "boards": boards,
        "can_create_board_post": can_create_post_in_any_board(request.user),
        "can_access_dashboard": has_dashboard_access(request.user),
    }
