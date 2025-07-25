# Create your views here.
# accounts/views.py
from django.views.generic.edit import FormView
from django.contrib.auth import authenticate, login
from django.urls import reverse_lazy
from .forms import LoginForm

class LoginView(FormView):
    template_name = "accounts/login.html"
    form_class = LoginForm
    success_url = reverse_lazy("index")  # 登录成功后的跳转

    def form_valid(self, form):
        username = form.cleaned_data["username"]
        password = form.cleaned_data["password"]
        user = authenticate(self.request, username=username, password=password)
        if user is not None:
            if user.is_active:
                login(self.request, user)
                return super().form_valid(form)
            else:
                form.add_error(None, "账号未激活，请联系管理员")
        else:
            form.add_error(None, "用户名或密码错误")
        return self.form_invalid(form)
