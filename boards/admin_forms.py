"""Forms for explicit super-admin break-glass operations."""

from django import forms


class MembershipBreakGlassDeactivateForm(forms.Form):
    reason = forms.CharField(
        label="应急原因",
        max_length=1000,
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "说明为什么无法先完成正常的 Manager 交接",
            }
        ),
    )
    confirmation = forms.CharField(
        label="精确确认短语",
        max_length=256,
        strip=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    code = forms.RegexField(
        regex=r"^\d{6}$",
        label="新的 Authenticator 动态验证码",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "placeholder": "000000",
            }
        ),
    )
