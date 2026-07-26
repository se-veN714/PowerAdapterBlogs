"""账户认证视图：登录。
"""
import hashlib
import logging

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic.edit import FormView
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.http import Http404
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, RedirectView, UpdateView

from Blogs.models import Post

from .forms import (
    AcceptAccountInvitationForm,
    AccountPasswordChangeForm,
    LoginForm,
    UserProfileForm,
)
from .models import AccountInvitation, MyUser, UserProfile
from .services import accept_account_invitation, invitation_token_digest

logger = logging.getLogger(__name__)


def _login_failure_key(request, username):
    """构造不暴露用户名和 IP 原文的失败计数 key。"""
    client_ip = getattr(request, 'client_ip', request.META.get('REMOTE_ADDR', 'unknown'))
    identity = f"{username.casefold()}|{client_ip}".encode('utf-8')
    return f"login-fail:{hashlib.sha256(identity).hexdigest()}"


def _record_login_failure(key):
    timeout = getattr(settings, 'LOGIN_LOCKOUT_SECONDS', 15 * 60)
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return 1


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
        user = self.request.user
        if user.is_authenticated and user.is_dashboard_user:
            return reverse("cus_admin:index")
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
        max_failures = getattr(settings, 'LOGIN_MAX_FAILURES', 5)
        lockout_seconds = getattr(settings, 'LOGIN_LOCKOUT_SECONDS', 15 * 60)
        if (cache.get(failure_key) or 0) >= max_failures:
            logger.warning("User 登录锁定: username=%s", username)
            form.add_error(None, f"登录失败次数过多，请在 {lockout_seconds // 60} 分钟后重试")
            return self.form_invalid(form)

        user = authenticate(self.request, username=username, password=password)
        if user is not None:
            if user.is_active:
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
            return render(request, self.template_name, {"invalid_invitation": True}, status=400)
        form = AcceptAccountInvitationForm(invitation.user)
        return render(request, self.template_name, {"form": form})

    def post(self, request, token):
        invitation = self._get_invitation(token)
        if invitation is None:
            return render(request, self.template_name, {"invalid_invitation": True}, status=400)

        form = AcceptAccountInvitationForm(invitation.user, request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        user = accept_account_invitation(
            token,
            form.cleaned_data["new_password1"],
            expected_invitation_id=invitation.pk,
        )
        if user is None:
            return render(request, self.template_name, {"invalid_invitation": True}, status=400)
        messages.success(request, "账号已激活，请使用刚设置的密码登录。")
        return redirect("accounts:login")


class MyProfileRedirectView(LoginRequiredMixin, RedirectView):
    """确保当前用户有 Profile，并跳转到统一公开 URL。"""

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile.get_absolute_url()


class ProfileDetailView(ListView):
    """展示作者明确公开的资料及其公开已发布文章。"""

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

        is_owner = self.request.user.is_authenticated and self.request.user.pk == user.pk
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
        return (
            Post.publicly_visible_posts()
            .filter(owner=self.profile_user)
            .select_related("owner", "owner__profile", "category")
            .order_by("-created_time")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["profile_user"] = self.profile_user
        context["profile"] = self.profile_user.profile
        context["is_profile_owner"] = (
            self.request.user.is_authenticated
            and self.request.user.pk == self.profile_user.pk
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


class AccountPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    """使用 Django 密码策略修改密码，并保持当前登录会话。"""

    form_class = AccountPasswordChangeForm
    template_name = "pages/accounts/password_change.html"

    def get_success_url(self):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile.get_absolute_url()

    def form_valid(self, form):
        response = super().form_valid(form)
        logger.info("用户密码已修改: user_id=%s", self.request.user.pk)
        messages.success(self.request, "密码已修改，当前设备保持登录。")
        return response
