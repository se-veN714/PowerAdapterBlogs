"""账户认证视图：登录。"""

import base64
import hashlib
import io
import logging
from urllib.parse import urlsplit

import pyotp
import qrcode
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic.edit import FormView
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.http import Http404, HttpResponseForbidden
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, RedirectView, UpdateView
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from Blogs.models import Post
from boards.policies import can_edit_post, can_submit_post

from .forms import (
    AcceptAccountInvitationForm,
    AccountPasswordChangeForm,
    LoginForm,
    MfaRecoveryForm,
    MfaRevokeForm,
    MfaChallengeTotpForm,
    PasswordEmailVerificationForm,
    TotpCodeForm,
    UserProfileForm,
)
from .authn.mfa_services import (
    MfaServiceError,
    confirm_totp_enrollment,
    consume_recovery_code_for_rebind,
    revoke_totp_device,
    start_totp_enrollment,
    verify_active_totp,
)
from .authn.mtls_services import MtlsServiceError, resolve_client_certificate
from .authn.mfa_session import (
    challenge_is_locked,
    clear_challenge_failures,
    get_pending_challenge,
    increment_pending_attempts,
    issue_pending_challenge,
    mark_enrollment_session,
    mark_privileged_session,
    mark_recovery_session,
    mfa_required_for_user,
    record_challenge_failure,
    recovery_session_is_valid,
)
from .models import AccountInvitation, MfaTotpDevice, MyUser, UserProfile
from .services import (
    PASSWORD_CODE_COOLDOWN,
    PASSWORD_CODE_EXPIRED,
    PASSWORD_CODE_INVALID,
    PASSWORD_CODE_LOCKED,
    PASSWORD_CODE_SEND_FAILED,
    PASSWORD_CODE_SEND_LIMIT,
    PASSWORD_CODE_SENT,
    PASSWORD_CODE_VERIFIED,
    EMAIL_PURPOSE_BOARD_ACCESS,
    EMAIL_PURPOSE_MFA_ENROLLMENT,
    EMAIL_PURPOSE_PASSWORD_CHANGE,
    accept_account_invitation,
    clear_email_verification,
    clear_password_email_verification,
    email_verification_code_pending,
    email_verification_code_remaining_seconds,
    email_verification_is_verified,
    email_verification_resend_remaining_seconds,
    invitation_token_digest,
    issue_email_verification_code,
    mark_email_verification_verified,
    password_email_is_verified,
    password_email_verification_remaining_seconds,
    verify_email_verification_code,
)

logger = logging.getLogger(__name__)


def _login_failure_key(request, username):
    """构造不暴露用户名和 IP 原文的失败计数 key。"""
    client_ip = getattr(
        request, "client_ip", request.META.get("REMOTE_ADDR", "unknown")
    )
    identity = f"{username.casefold()}|{client_ip}".encode("utf-8")
    return f"login-fail:{hashlib.sha256(identity).hexdigest()}"


def _record_login_failure(key):
    timeout = getattr(settings, "LOGIN_LOCKOUT_SECONDS", 15 * 60)
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return 1


@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class LoginView(FormView):
    """登录视图。

    已登录用户直接跳转首页；dashboard 用户登录后跳转后台。
    """

    template_name = "pages/accounts/login.html"
    form_class = LoginForm
    success_url = reverse_lazy("index")  # 默认跳转（非 dashboard 用户）

    def dispatch(self, request, *args, **kwargs):
        """已登录用户访问登录页直接重定向到首页。"""
        if request.user.is_authenticated:
            return redirect(reverse("index"))
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        """dashboard 用户登录后直接跳转后台，普通用户跳首页。"""
        requested_target = self.request.POST.get("next") or self.request.GET.get("next")
        if requested_target:
            from django.utils.http import url_has_allowed_host_and_scheme

            if url_has_allowed_host_and_scheme(
                requested_target,
                allowed_hosts={self.request.get_host()},
                require_https=self.request.is_secure(),
            ):
                return requested_target
        user = self.request.user
        if user.is_authenticated and user.is_dashboard_user:
            return reverse("dashboard:overview")
        return super().get_success_url()

    def form_valid(self, form):
        """验证表单并登录用户。

        Args:
            form: LoginForm 实例，含 username 和 password。

        Returns:
            HttpResponse: 登录成功重定向，失败返回表单页。
        """
        username = form.cleaned_data["username"]
        password = form.cleaned_data["password"]
        failure_key = _login_failure_key(self.request, username)
        max_failures = getattr(settings, "LOGIN_MAX_FAILURES", 5)
        lockout_seconds = getattr(settings, "LOGIN_LOCKOUT_SECONDS", 15 * 60)
        if (cache.get(failure_key) or 0) >= max_failures:
            logger.warning("User 登录锁定: username=%s", username)
            form.add_error(
                None, f"登录失败次数过多，请在 {lockout_seconds // 60} 分钟后重试"
            )
            return self.form_invalid(form)

        user = authenticate(self.request, username=username, password=password)
        if user is not None:
            if user.is_active:
                if settings.MFA_ENFORCEMENT_ENABLED and mfa_required_for_user(user):
                    if not MfaTotpDevice.objects.filter(
                        user=user,
                        status=MfaTotpDevice.Status.ACTIVE,
                    ).exists():
                        login(self.request, user)
                        mark_enrollment_session(self.request, user)
                        cache.delete(failure_key)
                        logger.info(
                            "User 首次 MFA 绑定登录: user_id=%s",
                            user.id,
                        )
                        return redirect("accounts:mfa-enrollment-email-verify")
                    target = self.get_success_url_for_user(user)
                    certificate_binding = None
                    if settings.MTLS_ENFORCEMENT_ENABLED and urlsplit(
                        target
                    ).path.startswith(reverse("admin:index")):
                        try:
                            certificate_binding = resolve_client_certificate(
                                self.request,
                                expected_user=user,
                            )
                        except MtlsServiceError:
                            form.add_error(
                                None, "客户端证书验证失败，无法进入系统后台。"
                            )
                            return self.form_invalid(form)
                    issue_pending_challenge(
                        self.request,
                        user=user,
                        backend=user.backend,
                        target=target,
                        certificate_binding=certificate_binding,
                    )
                    cache.delete(failure_key)
                    return redirect("accounts:mfa-challenge")
                login(self.request, user)
                cache.delete(failure_key)
                logger.info("User 登录: user_id=%s", user.id)
                return super().form_valid(form)
            logger.warning(
                "User 登录失败: username=%s reason=account_inactive", username
            )
            form.add_error(None, "账号未激活，请联系管理员")
        else:
            attempts = _record_login_failure(failure_key)
            logger.warning(
                "User 登录失败: username=%s reason=invalid_password attempts=%s",
                username,
                attempts,
            )
            form.add_error(None, "用户名或密码错误")
        return self.form_invalid(form)

    def get_success_url_for_user(self, user):
        requested_target = self.request.POST.get("next") or self.request.GET.get("next")
        if requested_target:
            from django.utils.http import url_has_allowed_host_and_scheme

            if url_has_allowed_host_and_scheme(
                requested_target,
                allowed_hosts={self.request.get_host()},
                require_https=self.request.is_secure(),
            ):
                return requested_target
        if user.is_dashboard_user or user.is_superuser:
            return reverse("dashboard:overview")
        return reverse("index")


class AcceptAccountInvitationView(View):
    template_name = "pages/accounts/accept_invitation.html"

    def _get_invitation(self, token):
        return (
            AccountInvitation.objects.select_related("user")
            .filter(
                token_digest=invitation_token_digest(token),
                accepted_at__isnull=True,
                expires_at__gt=timezone.now(),
                user__is_active=False,
            )
            .first()
        )

    def get(self, request, token):
        invitation = self._get_invitation(token)
        if invitation is None:
            return render(
                request, self.template_name, {"invalid_invitation": True}, status=400
            )
        form = AcceptAccountInvitationForm(invitation.user)
        return render(request, self.template_name, {"form": form})

    def post(self, request, token):
        invitation = self._get_invitation(token)
        if invitation is None:
            return render(
                request, self.template_name, {"invalid_invitation": True}, status=400
            )

        form = AcceptAccountInvitationForm(invitation.user, request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        user = accept_account_invitation(
            token,
            form.cleaned_data["new_password1"],
            expected_invitation_id=invitation.pk,
        )
        if user is None:
            return render(
                request, self.template_name, {"invalid_invitation": True}, status=400
            )
        messages.success(request, "账号已激活，请使用刚设置的密码登录。")
        return redirect("accounts:login")


class MyProfileRedirectView(LoginRequiredMixin, RedirectView):
    """确保当前用户有 Profile，并跳转到统一公开 URL。"""

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile.get_absolute_url()


class ProfileDetailView(ListView):
    """Public author page plus an owner-only post management projection."""

    template_name = "pages/accounts/profile_detail.html"
    context_object_name = "post_list"
    paginate_by = 10
    profile_user = None

    def _resolve_profile_user(self):
        user = (
            MyUser.objects.filter(
                username=self.kwargs["username"],
                is_active=True,
            )
            .select_related("profile")
            .first()
        )
        if user is None:
            raise Http404("作者主页不存在")

        is_owner = (
            self.request.user.is_authenticated and self.request.user.pk == user.pk
        )
        try:
            profile = user.profile
        except UserProfile.DoesNotExist:
            if not is_owner:
                raise Http404("作者主页不存在")
            profile = UserProfile.objects.create(user=user)
        if not profile.is_public and not is_owner:
            raise Http404("作者主页不存在")
        return user

    def get_queryset(self):
        self.profile_user = self._resolve_profile_user()
        is_owner = (
            self.request.user.is_authenticated
            and self.request.user.pk == self.profile_user.pk
        )
        if is_owner:
            queryset = Post.objects.filter(owner=self.profile_user).exclude(
                status=Post.STATUS_DELETE
            )
        else:
            queryset = Post.publicly_visible_posts().filter(owner=self.profile_user)
        return queryset.select_related(
            "owner", "owner__profile", "category"
        ).order_by("-created_time")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["profile_user"] = self.profile_user
        context["profile"] = self.profile_user.profile
        context["is_profile_owner"] = (
            self.request.user.is_authenticated
            and self.request.user.pk == self.profile_user.pk
        )
        context["mfa_settings_available"] = context[
            "is_profile_owner"
        ] and mfa_required_for_user(self.profile_user)
        context["show_profile_post_management"] = context["is_profile_owner"]
        context["profile_post_count_label"] = (
            "MY POSTS" if context["is_profile_owner"] else "PUBLIC POSTS"
        )
        if context["is_profile_owner"]:
            for post in context["post_list"]:
                post.can_edit = can_edit_post(self.request.user, post)
                post.can_submit = (
                    post.status == Post.STATUS_DRAFT
                    and can_submit_post(self.request.user, post)
                )
        return context


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    """编辑当前用户自己的公开资料。"""

    form_class = UserProfileForm
    template_name = "pages/accounts/profile_form.html"

    def get_object(self, queryset=None):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile

    def form_valid(self, form):
        response = super().form_valid(form)
        logger.info("用户资料已更新: user_id=%s", self.request.user.pk)
        messages.success(self.request, "个人资料已更新。")
        return response


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class AccountEmailVerificationView(LoginRequiredMixin, FormView):
    """Purpose-isolated mailbox challenge shared by sensitive account actions."""

    form_class = PasswordEmailVerificationForm
    template_name = "pages/accounts/password_email_verification.html"
    purpose = None
    verification_url_name = None
    success_url_name = None
    cancel_url_name = "accounts:my-profile"
    challenge_kicker = "SECURITY / EMAIL CHALLENGE"
    challenge_title = "验证账号邮箱"
    challenge_intro = "完成邮箱验证后才能继续当前操作。"
    terminal_command = "verify mailbox"
    required_permission = None

    def _purpose(self):
        if self.purpose not in {
            EMAIL_PURPOSE_PASSWORD_CHANGE,
            EMAIL_PURPOSE_BOARD_ACCESS,
            EMAIL_PURPOSE_MFA_ENROLLMENT,
        }:
            raise Http404("未知的邮箱验证用途")
        return self.purpose

    def _session_key(self):
        if not self.request.session.session_key:
            self.request.session.create()
        return self.request.session.session_key

    def _verification_url(self):
        return reverse(self.verification_url_name)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if self.required_permission and not request.user.has_perm(
                self.required_permission
            ):
                raise PermissionDenied("当前账号不能发起此邮箱验证。")
            if request.GET.get("restart") == "1":
                clear_email_verification(request, self._purpose())
            elif email_verification_is_verified(request, self._purpose()):
                return redirect(self.success_url_name)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") == "send":
            result = issue_email_verification_code(
                request.user,
                self._session_key(),
                self._purpose(),
            )
            message_map = {
                PASSWORD_CODE_SENT: (
                    messages.success,
                    "验证码已发送，请检查账号邮箱。",
                ),
                PASSWORD_CODE_COOLDOWN: (
                    messages.warning,
                    "发送过于频繁，请一分钟后再试。",
                ),
                PASSWORD_CODE_SEND_LIMIT: (
                    messages.error,
                    "本小时发送次数已用完，请稍后再试。",
                ),
                PASSWORD_CODE_SEND_FAILED: (
                    messages.error,
                    "邮件暂时发送失败，请稍后再试。",
                ),
            }
            handler, text = message_map[result]
            handler(request, text)
            return redirect(self.verification_url_name)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        result = verify_email_verification_code(
            self.request.user,
            self._session_key(),
            self._purpose(),
            form.cleaned_data["code"],
        )
        if result == PASSWORD_CODE_VERIFIED:
            mark_email_verification_verified(self.request, self._purpose())
            logger.info(
                "账号邮箱验证通过: user_id=%s purpose=%s",
                self.request.user.pk,
                self._purpose(),
            )
            return redirect(self.success_url_name)
        error_map = {
            PASSWORD_CODE_INVALID: "验证码不正确，请重新输入。",
            PASSWORD_CODE_EXPIRED: "验证码不存在或已过期，请重新发送。",
            PASSWORD_CODE_LOCKED: "错误次数已用完，请重新发送验证码。",
        }
        form.add_error("code", error_map[result])
        return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        email = self.request.user.email
        local, _, domain = email.partition("@")
        visible = local[:2]
        context["masked_email"] = f"{visible}{'*' * max(2, len(local) - 2)}@{domain}"
        context["code_sent"] = email_verification_code_pending(
            self.request.user.pk,
            self._session_key(),
            self._purpose(),
        )
        context["code_remaining"] = email_verification_code_remaining_seconds(
            self.request.user.pk,
            self._session_key(),
            self._purpose(),
        )
        context["resend_remaining"] = email_verification_resend_remaining_seconds(
            self.request.user.pk,
        )
        context["code_ttl_minutes"] = settings.PASSWORD_EMAIL_CODE_TTL_SECONDS // 60
        context["max_attempts"] = settings.PASSWORD_EMAIL_MAX_ATTEMPTS
        context["challenge_kicker"] = self.challenge_kicker
        context["challenge_title"] = self.challenge_title
        context["challenge_intro"] = self.challenge_intro
        context["terminal_command"] = self.terminal_command
        context["cancel_url"] = reverse(self.cancel_url_name)
        return context


class PasswordEmailVerificationView(AccountEmailVerificationView):
    """修改密码前，以短时邮件验证码确认当前账号控制权。"""

    purpose = EMAIL_PURPOSE_PASSWORD_CHANGE
    verification_url_name = "accounts:password-email-verify"
    success_url_name = "accounts:password-change"
    challenge_intro = "验证通过后，仍需输入当前密码才能修改。"
    terminal_command = "verify mailbox --purpose credential-rotation"


class BoardAccessEmailVerificationView(AccountEmailVerificationView):
    """提交 BoardAccessRequest 前确认当前邮箱控制权。"""

    purpose = EMAIL_PURPOSE_BOARD_ACCESS
    verification_url_name = "accounts:board-access-email-verify"
    success_url_name = "boards:access-requests"
    cancel_url_name = "boards:access-requests"
    challenge_title = "确认板块申请"
    challenge_intro = "验证通过后可在 10 分钟内提交一次板块权限申请。"
    terminal_command = "verify mailbox --purpose board-access"
    required_permission = "boards.apply_board_access"


class MfaEnrollmentEmailVerificationView(AccountEmailVerificationView):
    """首次或撤销后的 TOTP 绑定前确认账号邮箱控制权。"""

    purpose = EMAIL_PURPOSE_MFA_ENROLLMENT
    verification_url_name = "accounts:mfa-enrollment-email-verify"
    success_url_name = "accounts:mfa-settings"
    cancel_url_name = "accounts:my-profile"
    challenge_title = "确认动态验证码绑定"
    challenge_intro = "验证通过后可在 10 分钟内开始或继续绑定 Authenticator。"
    terminal_command = "verify mailbox --purpose mfa-enrollment"


class AccountPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    """邮箱验证后使用 Django 密码策略改密，并保持当前登录会话。"""

    form_class = AccountPasswordChangeForm
    template_name = "pages/accounts/password_change.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not password_email_is_verified(request):
            messages.info(request, "修改密码前，请先完成账号邮箱验证。")
            return redirect("accounts:password-email-verify")
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["email_verification_remaining"] = (
            password_email_verification_remaining_seconds(self.request)
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        clear_password_email_verification(self.request)
        logger.info("用户密码已修改: user_id=%s", self.request.user.pk)
        messages.success(self.request, "密码已修改，当前设备保持登录。")
        return response


@method_decorator(never_cache, name="dispatch")
@method_decorator(
    sensitive_post_parameters("current_password", "code"),
    name="dispatch",
)
class MfaSettingsView(LoginRequiredMixin, View):
    template_name = "pages/accounts/mfa_settings.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not mfa_required_for_user(request.user):
            raise Http404("动态验证码设置不可用")
        if request.user.is_authenticated:
            device = MfaTotpDevice.objects.filter(user=request.user).first()
            needs_email = device is None or device.status != MfaTotpDevice.Status.ACTIVE
            if needs_email and not email_verification_is_verified(
                request,
                EMAIL_PURPOSE_MFA_ENROLLMENT,
            ):
                messages.info(request, "首次绑定或设备撤销后，请先验证账号邮箱。")
                return redirect("accounts:mfa-enrollment-email-verify")
        return super().dispatch(request, *args, **kwargs)

    def _context(self, **extra):
        device = MfaTotpDevice.objects.filter(user=self.request.user).first()
        return {
            "device": device,
            "confirm_form": extra.pop("confirm_form", TotpCodeForm()),
            "revoke_form": extra.pop("revoke_form", MfaRevokeForm()),
            "recovery_rebind": recovery_session_is_valid(self.request),
            **extra,
        }

    def get(self, request):
        return render(request, self.template_name, self._context())

    def post(self, request):
        action = request.POST.get("action")
        if action == "start":
            try:
                enrollment = start_totp_enrollment(
                    user=request.user, actor=request.user
                )
            except MfaServiceError:
                messages.error(request, "暂时无法开始动态验证码绑定。")
                return render(request, self.template_name, self._context(), status=400)
            parsed = pyotp.parse_uri(enrollment.provisioning_uri)
            image = qrcode.make(enrollment.provisioning_uri)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            qr_data_uri = "data:image/png;base64," + base64.b64encode(
                buffer.getvalue()
            ).decode("ascii")
            return render(
                request,
                self.template_name,
                self._context(
                    enrollment=enrollment,
                    qr_data_uri=qr_data_uri,
                    manual_secret=parsed.secret,
                ),
            )
        if action == "revoke":
            form = MfaRevokeForm(request.POST)
            if not form.is_valid():
                return render(
                    request,
                    self.template_name,
                    self._context(revoke_form=form),
                    status=400,
                )
            try:
                revoke_totp_device(
                    target_user=request.user,
                    actor=request.user,
                    current_password=form.cleaned_data["current_password"],
                    totp_code=form.cleaned_data["code"],
                    reason="self_reset",
                )
            except MfaServiceError as exc:
                field = (
                    "current_password"
                    if exc.reason == "reset_not_allowed"
                    else "code"
                )
                form.add_error(field, "密码或动态验证码不正确，设备未撤销。")
                return render(
                    request,
                    self.template_name,
                    self._context(revoke_form=form),
                    status=400,
                )
            messages.success(request, "动态验证码设备已撤销，旧种子和恢复码均已销毁。")
            clear_email_verification(request, EMAIL_PURPOSE_MFA_ENROLLMENT)
            return redirect("accounts:mfa-settings")
        raise Http404("未知的动态验证码操作")


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("code"), name="dispatch")
class MfaConfirmEnrollmentView(LoginRequiredMixin, FormView):
    form_class = TotpCodeForm
    template_name = "pages/accounts/mfa_settings.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not email_verification_is_verified(
            request,
            EMAIL_PURPOSE_MFA_ENROLLMENT,
        ):
            messages.info(request, "确认绑定前，请先完成账号邮箱验证。")
            return redirect("accounts:mfa-enrollment-email-verify")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            confirmation = confirm_totp_enrollment(
                user=self.request.user,
                actor=self.request.user,
                code=form.cleaned_data["code"],
            )
        except MfaServiceError:
            form.add_error("code", "验证码无效、已过期或绑定状态已经改变。")
            return self.form_invalid(form)
        device = MfaTotpDevice.objects.get(pk=confirmation.device_id)
        mark_privileged_session(self.request, device)
        clear_email_verification(self.request, EMAIL_PURPOSE_MFA_ENROLLMENT)
        return render(
            self.request,
            "pages/accounts/mfa_recovery_codes.html",
            {"recovery_codes": confirmation.recovery_codes},
        )

    def form_invalid(self, form):
        device = MfaTotpDevice.objects.filter(user=self.request.user).first()
        return render(
            self.request,
            self.template_name,
            {
                "device": device,
                "confirm_form": form,
                "revoke_form": MfaRevokeForm(),
                "recovery_rebind": recovery_session_is_valid(self.request),
            },
            status=400,
        )


@method_decorator(never_cache, name="dispatch")
@method_decorator(
    sensitive_post_parameters("code", "recovery_code"),
    name="dispatch",
)
class MfaChallengeView(View):
    template_name = "pages/accounts/mfa_challenge.html"

    def _challenge(self):
        return get_pending_challenge(self.request)

    def _certificate_binding(self, challenge):
        if challenge.certificate_binding_id is None:
            return None
        try:
            binding = resolve_client_certificate(
                self.request,
                expected_user=challenge.user,
            )
        except MtlsServiceError:
            return False
        if (
            str(binding.pk) != challenge.certificate_binding_id
            or binding.auth_version != challenge.certificate_auth_version
        ):
            return False
        return binding

    @staticmethod
    def _can_remember_dashboard(challenge):
        return (
            challenge.certificate_binding_id is None
            and challenge.target.startswith("/dashboard/")
            and (
                challenge.user.is_dashboard_user
                or challenge.user.is_superuser
            )
        )

    def get(self, request):
        challenge = self._challenge()
        if challenge is None:
            messages.info(request, "动态验证码挑战不存在或已过期，请重新登录。")
            return redirect("accounts:login")
        if self._certificate_binding(challenge) is False:
            return HttpResponseForbidden("客户端证书验证失败。")
        return render(
            request,
            self.template_name,
            {
                "totp_form": MfaChallengeTotpForm(),
                "recovery_form": MfaRecoveryForm(),
                "can_remember_dashboard": self._can_remember_dashboard(challenge),
            },
        )

    def post(self, request):
        challenge = self._challenge()
        if challenge is None:
            return redirect("accounts:login")
        certificate_binding = self._certificate_binding(challenge)
        if certificate_binding is False:
            return HttpResponseForbidden("客户端证书验证失败。")
        if challenge_is_locked(request, challenge.user.pk):
            return render(
                request,
                self.template_name,
                {
                    "totp_form": MfaChallengeTotpForm(),
                    "recovery_form": MfaRecoveryForm(),
                    "locked": True,
                    "can_remember_dashboard": self._can_remember_dashboard(
                        challenge
                    ),
                },
                status=429,
            )
        action = request.POST.get("action", "totp")
        if action == "recovery":
            recovery_form = MfaRecoveryForm(request.POST)
            if recovery_form.is_valid():
                try:
                    device = consume_recovery_code_for_rebind(
                        user=challenge.user,
                        actor=challenge.user,
                        code=recovery_form.cleaned_data["recovery_code"],
                    )
                except MfaServiceError:
                    device = None
                if device is not None:
                    login(request, challenge.user, backend=challenge.backend)
                    mark_recovery_session(request, device)
                    clear_challenge_failures(request, challenge.user.pk)
                    return redirect("accounts:mfa-settings")
            attempts = record_challenge_failure(request, challenge.user.pk)
            increment_pending_attempts(request)
            recovery_form.add_error(None, "恢复码无效或已经使用。")
            return render(
                request,
                self.template_name,
                {
                    "totp_form": MfaChallengeTotpForm(),
                    "recovery_form": recovery_form,
                    "locked": attempts >= settings.MFA_CHALLENGE_MAX_ATTEMPTS,
                    "can_remember_dashboard": self._can_remember_dashboard(
                        challenge
                    ),
                },
                status=(
                    429 if attempts >= settings.MFA_CHALLENGE_MAX_ATTEMPTS else 400
                ),
            )

        totp_form = MfaChallengeTotpForm(request.POST)
        if totp_form.is_valid():
            try:
                device = verify_active_totp(
                    user=challenge.user,
                    actor=challenge.user,
                    code=totp_form.cleaned_data["code"],
                )
            except MfaServiceError:
                device = None
            if device is not None:
                if not request.user.is_authenticated:
                    login(request, challenge.user, backend=challenge.backend)
                mark_privileged_session(
                    request,
                    device,
                    certificate_binding=certificate_binding,
                    remember_dashboard=(
                        totp_form.cleaned_data["remember_dashboard"]
                        if self._can_remember_dashboard(challenge)
                        else None
                    ),
                )
                clear_challenge_failures(request, challenge.user.pk)
                return redirect(challenge.target)
        attempts = record_challenge_failure(request, challenge.user.pk)
        increment_pending_attempts(request)
        totp_form.add_error(None, "动态验证码无效、已使用或已过期。")
        return render(
            request,
            self.template_name,
            {
                "totp_form": totp_form,
                "recovery_form": MfaRecoveryForm(),
                "locked": attempts >= settings.MFA_CHALLENGE_MAX_ATTEMPTS,
                "can_remember_dashboard": self._can_remember_dashboard(challenge),
            },
            status=429 if attempts >= settings.MFA_CHALLENGE_MAX_ATTEMPTS else 400,
        )
