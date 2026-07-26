from django import forms

from boards.models import Board, BoardAccessRequest


class BoardAccessRequestForm(forms.ModelForm):
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
        super().__init__(*args, **kwargs)
        self.fields["board"].queryset = Board.objects.filter(is_active=True)
        self.fields["board"].empty_label = "请选择板块"
        self.fields["requested_role"].help_text = (
            "Contributor 可投稿，Editor 可维护自己的文章，Reviewer 负责审核；"
            "Manager 申请仅能由 superuser 批准。"
        )
