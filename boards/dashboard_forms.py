"""Forms for the Devenir Board Membership management surface."""

from django import forms
from django.contrib.auth import get_user_model

from boards.models import Board, BoardMembership


class MembershipMutationForm(forms.Form):
    reason = forms.CharField(
        label="变更原因",
        max_length=1000,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "说明为什么需要执行本次权限变更",
            }
        ),
    )
    code = forms.RegexField(
        regex=r"^\d{6}$",
        label="Authenticator 动态验证码",
        max_length=6,
        min_length=6,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "placeholder": "000000",
            }
        ),
    )


class MembershipGrantForm(MembershipMutationForm):
    board = forms.ModelChoiceField(
        label="板块",
        queryset=Board.objects.none(),
    )
    user = forms.ModelChoiceField(
        label="用户",
        queryset=get_user_model().objects.none(),
    )
    role = forms.ChoiceField(label="角色", choices=BoardMembership.Role.choices)

    field_order = ["board", "user", "role", "reason", "code"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["board"].queryset = Board.objects.filter(is_active=True).order_by(
            "sort_order", "pk"
        )
        self.fields["user"].queryset = (
            get_user_model()
            .objects.filter(is_active=True, is_superuser=False)
            .order_by("username", "pk")
        )


class MembershipRoleForm(MembershipMutationForm):
    role = forms.ChoiceField(label="新角色", choices=BoardMembership.Role.choices)
    field_order = ["role", "reason", "code"]


class MembershipDeactivateForm(MembershipMutationForm):
    pass


class ManagerTransferForm(MembershipMutationForm):
    DISPOSITION_CHOICES = (
        ("deactivate", "交接后停用原 Manager"),
        (BoardMembership.Role.CONTRIBUTOR, "降为投稿者"),
        (BoardMembership.Role.EDITOR, "降为编辑者"),
        (BoardMembership.Role.REVIEWER, "降为审核者"),
    )

    target_user = forms.ModelChoiceField(
        label="接任用户",
        queryset=get_user_model().objects.none(),
    )
    old_disposition = forms.ChoiceField(
        label="原 Manager 的交接后状态",
        choices=DISPOSITION_CHOICES,
    )
    field_order = ["target_user", "old_disposition", "reason", "code"]

    def __init__(self, *args, membership=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = get_user_model().objects.filter(
            is_active=True,
            is_superuser=False,
        )
        if membership is not None:
            queryset = queryset.exclude(pk=membership.user_id)
        self.fields["target_user"].queryset = queryset.order_by("username", "pk")
