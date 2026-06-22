"""账户认证视图：登录。
"""
import logging

from django.shortcuts import redirect
from django.views.generic.edit import FormView
from django.contrib.auth import authenticate, login
from django.urls import reverse, reverse_lazy
from .forms import LoginForm

logger = logging.getLogger(__name__)


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
        user = authenticate(self.request, username=username, password=password)
        if user is not None:
            if user.is_active:
                login(self.request, user)
                logger.info("User 登录: user_id=%s", user.id)
                return super().form_valid(form)
            logger.warning(
                "User 登录失败: username=%s reason=account_inactive", username
            )
            form.add_error(None, "账号未激活，请联系管理员")
        else:
            logger.warning(
                "User 登录失败: username=%s reason=invalid_password", username
            )
            form.add_error(None, "用户名或密码错误")
        return self.form_invalid(form)
