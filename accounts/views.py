"""账户认证视图：登录。
"""
import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import redirect
from django.views.generic.edit import FormView
from django.contrib.auth import authenticate, login
from django.urls import reverse, reverse_lazy
from .forms import LoginForm

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
