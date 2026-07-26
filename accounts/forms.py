# -*- coding: utf-8 -*-
# @File    : forms.py
# @Time    : 2025/7/11 12:03
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了accounts-forms功能的类和函数。
"""

# here put the import lib
from django import forms
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm

from .models import MyUser, UserProfile


class LoginForm(forms.Form):
    username = forms.CharField(label="用户名")
    password = forms.CharField(label="口令", widget=forms.PasswordInput)


class AccountInvitationCreationForm(forms.ModelForm):
    """管理员只发放账号，密码由受邀者通过邮件自行设置。"""

    # AbstractBaseUser.password 在模型层必填；保留隐藏字段以通过 ModelForm
    # 的模型校验，但永远忽略其输入并写入 unusable password。
    password = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = MyUser
        fields = ("username", "email", "password")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = False
        user.set_unusable_password()
        if commit:
            user.save()
        return user


class AcceptAccountInvitationForm(SetPasswordForm):
    """邀请接受页的密码设置表单。"""


class UserProfileForm(forms.ModelForm):
    """只允许用户修改明确公开的 Profile 字段。"""

    avatar = forms.ImageField(
        required=False,
        label="头像",
        help_text="支持 JPEG、PNG、GIF、WEBP，最大 5MB。",
        error_messages={"invalid_image": "上传文件不是有效图片。"},
    )

    class Meta:
        model = UserProfile
        fields = (
            "display_name",
            "bio",
            "avatar",
            "website",
            "github_url",
            "location",
            "is_public",
        )
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 6}),
        }
        help_texts = {
            "is_public": "开启后，任何人都可以查看本页列出的资料和你的公开文章。",
        }


class AccountPasswordChangeForm(PasswordChangeForm):
    """前台账号密码修改表单。"""


class PasswordEmailVerificationForm(forms.Form):
    """修改密码前的邮箱一次性验证码。"""

    code = forms.RegexField(
        regex=r"^\d{6}$",
        label="邮箱验证码",
        max_length=6,
        min_length=6,
        error_messages={"invalid": "请输入邮件中的 6 位数字验证码。"},
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "pattern": "[0-9]{6}",
                "placeholder": "000000",
            }
        ),
    )
