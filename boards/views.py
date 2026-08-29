"""Boards 应用的视图和上下文处理器。

将活跃的首页板块数据注入所有模板上下文，供 base.html / index.html 使用。
"""

from urllib.parse import urlencode

from django.conf import settings

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import FormView, ListView, TemplateView

from Blogs.models import Category, Post
from PowerAdapterBlogs.base_admin import has_dashboard_access
from accounts.authn.mfa_services import MfaServiceError, verify_active_totp
from accounts.authn.mfa_session import (
    challenge_is_locked,
    clear_challenge_failures,
    record_challenge_failure,
)
from accounts.models import MfaTotpDevice
from accounts.services import (
    EMAIL_PURPOSE_BOARD_ACCESS,
    clear_email_verification,
    email_verification_is_verified,
    email_verification_remaining_seconds,
)
from boards.board_index import (
    ASSEMBLERS,
    BOARD_TEMPLATES,
    prepare_skate_clips,
    renderable_boards,
)
from boards.forms import BoardAccessRequestForm
from boards.models import (
    Board,
    BoardAccessRequest,
    BoardMembership,
    SkateClip,
    SkateHomie,
)
from boards.policies import (
    boards_manageable_by,
    can_access_post_admin,
    can_create_post_for_board_category,
    can_create_post_in_any_board,
    can_view_review_queue,
)
from boards.services import submit_board_access_request, withdraw_board_membership


BOARD_MANAGEMENT_DESTINATIONS = {
    "skateboard": (
        ("Skateboard · Clips", "boards:skate-manage-list", ()),
    ),
    "music": (
        ("Music · Spotify", "boards:music-period-list", ("spotify",)),
        ("Music · Apple Music", "boards:music-period-list", ("apple",)),
        ("Music · Artists", "boards:music-artist-list", ()),
    ),
    "coding": (
        ("Coding · Projects", "boards:coding-manage-list", ()),
        ("Coding · Principles", "boards:coding-principle-list", ()),
        ("Coding · Experiments", "boards:coding-experiment-list", ()),
    ),
}


def board_management_links(user, boards):
    """Return only management destinations authorized by Board Policy."""
    manageable_slugs = set(
        boards_manageable_by(user, boards).values_list("slug", flat=True)
    )
    return [
        {
            "board_slug": slug,
            "label": label,
            "url": reverse(url_name, args=args),
        }
        for slug, destinations in BOARD_MANAGEMENT_DESTINATIONS.items()
        if slug in manageable_slugs
        for label, url_name, args in destinations
    ]


def _url_with_query(url_name, *, query=None, kwargs=None):
    url = reverse(url_name, kwargs=kwargs)
    return f"{url}?{urlencode(query)}" if query else url


def board_index_shared_context(request, board):
    """Build the public post stream and Policy-derived participation CTA."""
    category = board.category
    category_is_public = bool(
        category and category.status == Category.STATUS_NORMAL
    )
    if category_is_public:
        board_posts = list(
            Post.publicly_visible_posts()
            .filter(category=category)
            .select_related("category", "owner")
            .order_by("-created_time", "-pk")[:5]
        )
        board_posts_url = reverse(
            "Blogs:category_list",
            kwargs={"category_id": category.pk},
        )
    else:
        board_posts = []
        board_posts_url = ""

    user = request.user
    board_url = reverse("boards:index", kwargs={"slug": board.slug})
    if not user.is_authenticated:
        participation = {
            "state": "anonymous",
            "url": _url_with_query(
                "accounts:login",
                query={"next": board_url},
            ),
            "label": "登录后申请",
        }
    else:
        membership = BoardMembership.objects.filter(
            board=board,
            user=user,
        ).first()
        if user.is_superuser or (membership and membership.is_active):
            if can_create_post_for_board_category(user, board):
                participation_url = _url_with_query(
                    "Blogs:post_create",
                    query={"board": board.slug},
                )
                participation_label = "新建板块文章"
            elif can_view_review_queue(user, board):
                participation_url = _url_with_query(
                    "Blogs:review_workspace",
                    query={"board": board.slug},
                )
                participation_label = "进入稿件审核"
            else:
                participation_url = _url_with_query(
                    "boards:access-requests",
                    query={"board": board.slug},
                )
                participation_label = "查看板块权限"
            participation = {
                "state": "member",
                "url": participation_url,
                "label": participation_label,
            }
        elif BoardAccessRequest.objects.filter(
            board=board,
            applicant=user,
            status=BoardAccessRequest.Status.PENDING,
        ).exists():
            participation = {
                "state": "pending",
                "url": _url_with_query(
                    "boards:access-requests",
                    query={"board": board.slug},
                ),
                "label": "查看申请进度",
            }
        elif membership and not membership.is_active:
            participation = {"state": "suspended", "url": "", "label": ""}
        elif user.has_perm("boards.apply_board_access"):
            participation = {
                "state": "eligible",
                "url": _url_with_query(
                    "boards:access-requests",
                    query={"board": board.slug},
                ),
                "label": "申请板块权限",
            }
        else:
            participation = {"state": "suspended", "url": "", "label": ""}

    return {
        "board_posts": board_posts,
        "board_posts_url": board_posts_url,
        "board_participation_state": participation["state"],
        "board_participation_url": participation["url"],
        "board_participation_label": participation["label"],
    }


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

    def _has_active_totp(self):
        if not hasattr(self, "_active_totp_cache"):
            self._active_totp_cache = MfaTotpDevice.objects.filter(
                user=self.request.user,
                status=MfaTotpDevice.Status.ACTIVE,
            ).exists()
        return self._active_totp_cache

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["require_totp"] = self._has_active_totp()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        board_slug = self.request.GET.get("board", "")[:64]
        if board_slug:
            board = Board.objects.filter(slug=board_slug, is_active=True).first()
            if board is not None:
                initial["board"] = board
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["access_requests"] = BoardAccessRequest.objects.filter(
            applicant=self.request.user
        ).select_related("board", "reviewed_by")
        context["active_memberships"] = BoardMembership.objects.filter(
            user=self.request.user,
            is_active=True,
            board__is_active=True,
        ).select_related("board").order_by("board__sort_order", "board__name")
        context["show_submission_dialog"] = self.request.session.pop(
            "board_access_request_submitted",
            False,
        )
        context["totp_required"] = self._has_active_totp()
        context["email_verified"] = (
            not context["totp_required"]
            and email_verification_is_verified(
                self.request,
                EMAIL_PURPOSE_BOARD_ACCESS,
            )
        )
        context["verification_ready"] = (
            context["totp_required"] or context["email_verified"]
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
        if self._has_active_totp():
            if challenge_is_locked(self.request, self.request.user.pk):
                form.add_error(
                    "totp_code",
                    "动态验证码尝试次数过多，请在冷却期后重试。",
                )
                return self.render_to_response(
                    self.get_context_data(form=form),
                    status=429,
                )
            try:
                verify_active_totp(
                    user=self.request.user,
                    actor=self.request.user,
                    code=form.cleaned_data["totp_code"],
                )
            except MfaServiceError:
                attempts = record_challenge_failure(
                    self.request,
                    self.request.user.pk,
                )
                form.add_error(
                    "totp_code",
                    "动态验证码无效、已使用或已过期。",
                )
                return self.render_to_response(
                    self.get_context_data(form=form),
                    status=(
                        429
                        if attempts >= settings.MFA_CHALLENGE_MAX_ATTEMPTS
                        else 200
                    ),
                )
            clear_challenge_failures(self.request, self.request.user.pk)
        elif not email_verification_is_verified(
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
        if not self._has_active_totp():
            clear_email_verification(self.request, EMAIL_PURPOSE_BOARD_ACCESS)
        self.request.session["board_access_request_submitted"] = True
        messages.success(self.request, "板块权限申请已提交。")
        return super().form_valid(form)


@login_required
@require_POST
def withdraw_membership(request, pk):
    """Consume a short email grant and deactivate the caller's Membership."""
    if not email_verification_is_verified(request, EMAIL_PURPOSE_BOARD_ACCESS):
        messages.info(request, "退出板块前，请先完成账号邮箱验证。")
        return redirect("accounts:board-access-email-verify")
    membership = get_object_or_404(
        BoardMembership,
        pk=pk,
        user=request.user,
    )
    try:
        withdrawn = withdraw_board_membership(
            membership=membership,
            actor=request.user,
        )
    except PermissionDenied as exc:
        messages.error(request, str(exc))
    except ValidationError as exc:
        messages.warning(request, exc.messages[0])
    else:
        clear_email_verification(request, EMAIL_PURPOSE_BOARD_ACCESS)
        messages.success(request, f"已退出 {withdrawn.board.name} 板块。")
    return redirect("boards:access-requests")


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
        board = get_object_or_404(renderable_boards(), slug=slug)
        self.board = board
        self.template_name = BOARD_TEMPLATES[slug]
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["board"] = self.board
        context.update(ASSEMBLERS[self.board.slug](self.board))
        context.update(board_index_shared_context(self.request, self.board))
        context["board_manage_links"] = board_management_links(
            self.request.user,
            Board.objects.filter(pk=self.board.pk),
        )
        if self.board.slug == "skateboard":
            context["amap_enabled"] = bool(
                settings.AMAP_JS_API_ENABLED
                and settings.AMAP_JS_API_KEY
                and settings.AMAP_JS_SECURITY_JSCODE
            )
            context["amap_api_key"] = settings.AMAP_JS_API_KEY
            context["amap_service_host"] = settings.AMAP_JS_SERVICE_HOST
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
            SkateClip.objects.filter(homie=homie, is_public=True)
            .select_related("homie", "media")
            .order_by("order", "pk")
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
            .select_related("homie", "media")
            .order_by(F("filmed_at").desc(nulls_last=True), "-created_at", "-pk")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["board"] = self.board
        prepare_skate_clips(context["clips"])
        # WATCH CLIP 对话框（_player_dialog.html）的 AMap 迷你图配置，与索引页保持一致
        context["amap_enabled"] = bool(
            settings.AMAP_JS_API_ENABLED
            and settings.AMAP_JS_API_KEY
            and settings.AMAP_JS_SECURITY_JSCODE
        )
        context["amap_api_key"] = settings.AMAP_JS_API_KEY
        context["amap_service_host"] = settings.AMAP_JS_SERVICE_HOST
        return context


def boards_context(request):
    """上下文处理器：注入活跃的首页板块列表。

    按 sort_order 排序，仅供首页 editorial-section 遍历渲染。
    返回 board 对象，模板可通过 board.glitch_color 等属性使用。
    """
    boards = renderable_boards()
    from moderation.policies import can_access_moderation_center

    return {
        "boards": boards,
        "board_management_links": board_management_links(request.user, boards),
        "can_create_board_post": can_create_post_in_any_board(request.user),
        "can_access_review_workspace": can_access_post_admin(request.user),
        "can_access_dashboard": has_dashboard_access(request.user),
        "can_access_moderation_center": can_access_moderation_center(request.user),
    }
