# Create your views here.
# accounts/views.py
import logging

from django.views.generic.edit import FormView
from django.contrib.auth import authenticate, login
from django.urls import reverse, reverse_lazy
from .forms import LoginForm

logger = logging.getLogger(__name__)


class LoginView(FormView):
    template_name = "accounts/login.html"
    form_class = LoginForm
    success_url = reverse_lazy("index")  # 默认跳转（非 dashboard 用户）

    def get_success_url(self):
        """dashboard 用户登录后直接跳转后台，普通用户跳首页"""
        user = self.request.user
        if user.is_authenticated and user.is_dashboard_user:
            return reverse("cus_admin:index")  # AdminSite 的 URL 通过 namespace:name 反向解析
        return super().get_success_url()

    def form_valid(self, form):
        username = form.cleaned_data["username"]
        password = form.cleaned_data["password"]
        user = authenticate(self.request, username=username, password=password)
        if user is not None:
            if user.is_active:
                login(self.request, user)
                logger.info(f"User 登录: user_id={user.id}")
                return super().form_valid(form)
            else:
                logger.warning(f"User 登录失败: username={username} reason=account_inactive")
                form.add_error(None, "账号未激活，请联系管理员")
        else:
            logger.warning(f"User 登录失败: username={username} reason=invalid_password")
            form.add_error(None, "用户名或密码错误")
        return self.form_invalid(form)
