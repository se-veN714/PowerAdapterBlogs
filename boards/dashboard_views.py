"""Devenir Dashboard views for full-site Board Membership management."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import FormView, ListView

from PowerAdapterBlogs.base_admin import has_dashboard_access
from accounts.authn.mfa_session import dashboard_session_is_valid
from boards.dashboard_forms import (
    ManagerTransferForm,
    MembershipDeactivateForm,
    MembershipGrantForm,
    MembershipRoleForm,
)
from boards.membership_step_up import (
    MANAGE_MEMBERSHIP_PERMISSION,
    MembershipStepUpError,
    issue_membership_step_up,
)
from boards.models import Board, BoardMembership, BoardMembershipEvent
from boards.services import (
    MEMBERSHIP_ACTION_CHANGE_ROLE,
    MEMBERSHIP_ACTION_DEACTIVATE,
    MEMBERSHIP_ACTION_GRANT,
    MEMBERSHIP_ACTION_REACTIVATE,
    MEMBERSHIP_ACTION_TRANSFER_MANAGER,
    change_board_membership_role,
    deactivate_board_membership,
    grant_board_membership,
    membership_step_up_target,
    reactivate_board_membership,
    transfer_board_manager,
)


class DashboardMembershipAccessMixin(LoginRequiredMixin):
    login_url = "accounts:login"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not has_dashboard_access(request.user):
            raise PermissionDenied("当前账号不能进入站长工作台。")
        if not request.user.has_perm(MANAGE_MEMBERSHIP_PERMISSION):
            raise PermissionDenied("当前账号没有全站板块成员管理权限。")
        if not dashboard_session_is_valid(request):
            raise PermissionDenied("当前特权 Session 无效，请重新完成工作台登录验证。")
        return super().dispatch(request, *args, **kwargs)


@method_decorator(never_cache, name="dispatch")
class DashboardMembershipListView(DashboardMembershipAccessMixin, ListView):
    template_name = "pages/dashboard/memberships.html"
    context_object_name = "memberships"
    paginate_by = 25

    def get_queryset(self):
        queryset = BoardMembership.objects.select_related(
            "board", "user", "created_by"
        ).order_by("board__sort_order", "user__username", "pk")
        query = self.request.GET.get("q", "").strip()
        board = self.request.GET.get("board", "").strip()
        role = self.request.GET.get("role", "").strip()
        status = self.request.GET.get("status", "active").strip()
        if query:
            queryset = queryset.filter(
                Q(user__username__icontains=query)
                | Q(user__email__icontains=query)
                | Q(board__name__icontains=query)
                | Q(board__slug__icontains=query)
            )
        if board.isdigit():
            queryset = queryset.filter(board_id=int(board))
        if role in {value for value, _label in BoardMembership.Role.choices}:
            queryset = queryset.filter(role=role)
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query_params = self.request.GET.copy()
        query_params.pop("page", None)
        context.update(
            {
                "boards": Board.objects.order_by("sort_order", "pk"),
                "role_choices": BoardMembership.Role.choices,
                "selected_q": self.request.GET.get("q", "").strip(),
                "selected_board": self.request.GET.get("board", "").strip(),
                "selected_role": self.request.GET.get("role", "").strip(),
                "selected_status": self.request.GET.get("status", "active").strip(),
                "event_count": BoardMembershipEvent.objects.count(),
                "query_string": query_params.urlencode(),
            }
        )
        return context


@method_decorator(never_cache, name="dispatch")
class DashboardMembershipEventListView(DashboardMembershipAccessMixin, ListView):
    template_name = "pages/dashboard/membership_events.html"
    context_object_name = "events"
    paginate_by = 30

    def get_membership(self):
        membership_id = self.kwargs.get("pk")
        if membership_id is None:
            return None
        if not hasattr(self, "_event_membership"):
            self._event_membership = get_object_or_404(
                BoardMembership.objects.select_related("board", "user"),
                pk=membership_id,
            )
        return self._event_membership

    def get_queryset(self):
        queryset = BoardMembershipEvent.objects.select_related(
            "membership",
            "access_request",
        )
        membership = self.get_membership()
        if membership is not None:
            queryset = queryset.filter(membership_id=membership.pk)

        query = self.request.GET.get("q", "").strip()
        board = self.request.GET.get("board", "").strip()
        event_type = self.request.GET.get("event_type", "").strip()
        source = self.request.GET.get("source", "").strip()
        if query:
            queryset = queryset.filter(
                Q(username_snapshot__icontains=query)
                | Q(actor_username_snapshot__icontains=query)
                | Q(reason__icontains=query)
            )
        if board:
            queryset = queryset.filter(board_slug_snapshot__iexact=board)
        if event_type in {
            value for value, _label in BoardMembershipEvent.EventType.choices
        }:
            queryset = queryset.filter(event_type=event_type)
        if source in {value for value, _label in BoardMembershipEvent.Source.choices}:
            queryset = queryset.filter(source=source)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query_params = self.request.GET.copy()
        query_params.pop("page", None)
        context.update(
            {
                "membership": self.get_membership(),
                "event_type_choices": BoardMembershipEvent.EventType.choices,
                "source_choices": BoardMembershipEvent.Source.choices,
                "selected_q": self.request.GET.get("q", "").strip(),
                "selected_board": self.request.GET.get("board", "").strip(),
                "selected_event_type": self.request.GET.get(
                    "event_type", ""
                ).strip(),
                "selected_source": self.request.GET.get("source", "").strip(),
                "query_string": query_params.urlencode(),
            }
        )
        return context


class DashboardMembershipMutationView(DashboardMembershipAccessMixin, FormView):
    template_name = "pages/dashboard/membership_action.html"
    action = ""
    title = "成员权限操作"
    submit_label = "验证并执行"
    warning = "该操作会写入不可变关系型事件和 Mongo HMAC 审计镜像。"
    success_message = "板块成员权限已更新。"

    def get_success_url(self):
        return reverse("board-dashboard:memberships")

    def get_membership(self):
        if not hasattr(self, "_membership"):
            self._membership = get_object_or_404(
                BoardMembership.objects.select_related("board", "user"),
                pk=self.kwargs["pk"],
            )
        return self._membership

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "action_title": self.title,
                "submit_label": self.submit_label,
                "warning": self.warning,
                "membership": (
                    self.get_membership() if "pk" in self.kwargs else None
                ),
            }
        )
        return context

    def step_up(self, *, target, code):
        return issue_membership_step_up(
            request=self.request,
            action=self.action,
            target=target,
            code=code,
        )

    def add_service_error(self, form, exc):
        if isinstance(exc, MembershipStepUpError):
            if exc.reason == "locked":
                message = "失败次数已达上限，请等待冷却后再试。"
            elif exc.reason == "privileged_session_required":
                message = "当前特权 Session 无效，请重新完成工作台登录验证。"
            else:
                message = "动态验证码无效、已使用或已过期。"
            form.add_error("code", message)
            return
        detail = " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        form.add_error(None, detail)


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class DashboardMembershipGrantView(DashboardMembershipMutationView):
    form_class = MembershipGrantForm
    action = MEMBERSHIP_ACTION_GRANT
    title = "直接授予板块权限"
    warning = "仅用于首位 Manager、明确授权或紧急纠错；存在待审核申请时会拒绝。"
    success_message = "板块权限已授予。"

    def form_valid(self, form):
        board = form.cleaned_data["board"]
        user = form.cleaned_data["user"]
        target = membership_step_up_target(
            action=self.action,
            board_id=board.pk,
            user_id=user.pk,
        )
        try:
            capability = self.step_up(target=target, code=form.cleaned_data["code"])
            grant_board_membership(
                request=self.request,
                actor=self.request.user,
                board=board,
                user=user,
                role=form.cleaned_data["role"],
                reason=form.cleaned_data["reason"],
                capability=capability,
            )
        except (MembershipStepUpError, ValidationError) as exc:
            self.add_service_error(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


class MembershipObjectMutationView(DashboardMembershipMutationView):
    def get_initial(self):
        initial = super().get_initial()
        initial["role"] = self.get_membership().role
        return initial

    def bound_target(self, *, extra=""):
        return membership_step_up_target(
            action=self.action,
            membership_id=self.get_membership().pk,
            extra=extra,
        )


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class DashboardMembershipRoleView(MembershipObjectMutationView):
    form_class = MembershipRoleForm
    action = MEMBERSHIP_ACTION_CHANGE_ROLE
    title = "调整板块角色"

    def form_valid(self, form):
        target = self.bound_target()
        try:
            capability = self.step_up(target=target, code=form.cleaned_data["code"])
            change_board_membership_role(
                request=self.request,
                actor=self.request.user,
                membership=self.get_membership(),
                role=form.cleaned_data["role"],
                reason=form.cleaned_data["reason"],
                capability=capability,
            )
        except (MembershipStepUpError, ValidationError) as exc:
            self.add_service_error(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class DashboardMembershipDeactivateView(MembershipObjectMutationView):
    form_class = MembershipDeactivateForm
    action = MEMBERSHIP_ACTION_DEACTIVATE
    title = "停用板块成员"
    warning = "停用立即撤销该 Board 的全部角色能力；最后一名 Manager 必须先交接。"

    def form_valid(self, form):
        target = self.bound_target()
        try:
            capability = self.step_up(target=target, code=form.cleaned_data["code"])
            deactivate_board_membership(
                request=self.request,
                actor=self.request.user,
                membership=self.get_membership(),
                reason=form.cleaned_data["reason"],
                capability=capability,
            )
        except (MembershipStepUpError, ValidationError) as exc:
            self.add_service_error(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class DashboardMembershipReactivateView(MembershipObjectMutationView):
    form_class = MembershipRoleForm
    action = MEMBERSHIP_ACTION_REACTIVATE
    title = "恢复板块成员"
    warning = "恢复前会再次检查账号、Board 和待审核申请，并明确写入恢复后的角色。"

    def form_valid(self, form):
        target = self.bound_target()
        try:
            capability = self.step_up(target=target, code=form.cleaned_data["code"])
            reactivate_board_membership(
                request=self.request,
                actor=self.request.user,
                membership=self.get_membership(),
                role=form.cleaned_data["role"],
                reason=form.cleaned_data["reason"],
                capability=capability,
            )
        except (MembershipStepUpError, ValidationError) as exc:
            self.add_service_error(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class DashboardManagerTransferView(MembershipObjectMutationView):
    form_class = ManagerTransferForm
    action = MEMBERSHIP_ACTION_TRANSFER_MANAGER
    title = "Manager 原子交接"
    warning = "系统会先确认接任者，再在同一事务中降级或停用原 Manager。"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["membership"] = self.get_membership()
        return kwargs

    def form_valid(self, form):
        replacement = form.cleaned_data["target_user"]
        disposition = form.cleaned_data["old_disposition"]
        target = self.bound_target(extra=f"to:{replacement.pk}:{disposition}")
        try:
            capability = self.step_up(target=target, code=form.cleaned_data["code"])
            transfer_board_manager(
                request=self.request,
                actor=self.request.user,
                membership=self.get_membership(),
                target_user=replacement,
                old_disposition=disposition,
                reason=form.cleaned_data["reason"],
                capability=capability,
            )
        except (MembershipStepUpError, ValidationError) as exc:
            self.add_service_error(form, exc)
            return self.form_invalid(form)
        messages.success(self.request, "Manager 交接已完成。")
        return redirect(self.get_success_url())
