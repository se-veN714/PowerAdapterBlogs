from django import forms

from boards.models import Board, BoardAccessRequest


class BoardAccessRequestForm(forms.ModelForm):
    totp_code = forms.RegexField(
        regex=r"^\d{6}$",
        required=False,
        label="动态验证码",
        max_length=6,
        min_length=6,
        error_messages={"invalid": "请输入 Authenticator 中的 6 位动态验证码。"},
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "pattern": "[0-9]{6}",
                "placeholder": "000000",
            }
        ),
    )

    class Meta:
        model = BoardAccessRequest
        fields = ("board", "requested_role", "reason")
        widgets = {
            "reason": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "请简要说明希望参与的内容或职责（可选）",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        require_totp = kwargs.pop("require_totp", False)
        super().__init__(*args, **kwargs)
        if require_totp:
            self.fields["totp_code"].required = True
            self.fields["totp_code"].help_text = (
                "使用已绑定 Authenticator 的当前验证码；每个时间步只能使用一次。"
            )
        else:
            self.fields.pop("totp_code")
        self.fields["board"].queryset = Board.objects.filter(is_active=True)
        self.fields["board"].empty_label = "请选择板块"
        self.fields["requested_role"].help_text = (
            "Contributor 可投稿，Editor 可维护自己的文章，Reviewer 负责审核；"
            "Manager 申请仅能由 superuser 批准。"
        )


class BoardMembershipWithdrawForm(forms.Form):
    totp_code = forms.RegexField(
        regex=r"^\d{6}$",
        label="动态验证码",
        max_length=6,
        min_length=6,
        error_messages={"invalid": "请输入 Authenticator 中的 6 位动态验证码。"},
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "pattern": "[0-9]{6}",
                "placeholder": "000000",
                "aria-label": "退出板块动态验证码",
            }
        ),
    )
