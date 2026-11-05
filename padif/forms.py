from typing import Any

from django import forms

from .models import Annotation, AnnotationReply, Document, Version


class DocumentUploadForm(forms.Form):
    title = forms.CharField(label="标题", max_length=200, required=False)
    markdown_file = forms.FileField(
        label="Markdown 文件",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".md,.markdown,text/markdown"}
        ),
    )
    commit_message = forms.CharField(
        label="初始说明",
        max_length=300,
        initial="初始导入",
    )


class VersionCommitForm(forms.Form):
    content = forms.CharField(label="正文", widget=forms.Textarea)
    commit_message = forms.CharField(label="本次修改", max_length=300)
    version_kind = forms.ChoiceField(label="版本级别", choices=Version.Kind.choices)


class VersionUploadForm(forms.Form):
    markdown_file = forms.FileField(
        label="Markdown 文件",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".md,.markdown,text/markdown"}
        ),
    )
    commit_message = forms.CharField(label="本次修改", max_length=300)
    version_kind = forms.ChoiceField(label="版本级别", choices=Version.Kind.choices)


class DiffSelectionForm(forms.Form):
    from_version = forms.ModelChoiceField(label="旧版本", queryset=Version.objects.none())
    to_version = forms.ModelChoiceField(label="新版本", queryset=Version.objects.none())
    mode = forms.ChoiceField(
        label="视图",
        choices=(("inline", "行内"), ("split", "并排"), ("stats", "统计")),
    )

    def __init__(
        self,
        *args: Any,
        document: Document,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        versions = document.versions.select_related("created_by").all()
        self.fields["from_version"].queryset = versions
        self.fields["to_version"].queryset = versions

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if cleaned.get("from_version") == cleaned.get("to_version"):
            raise forms.ValidationError("请选择两个不同版本。")
        return cleaned


class AnnotationForm(forms.ModelForm):
    class Meta:
        model = Annotation
        fields = ("kind", "body", "start_line", "end_line", "selected_text")
        widgets = {
            "body": forms.Textarea(attrs={"rows": 4}),
            "selected_text": forms.HiddenInput(),
        }
        labels = {
            "kind": "批注类型",
            "body": "内容",
            "start_line": "起始行",
            "end_line": "结束行",
            "selected_text": "选中文字",
        }

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if (
            cleaned.get("start_line")
            and cleaned.get("end_line")
            and cleaned["end_line"] < cleaned["start_line"]
        ):
            raise forms.ValidationError("结束行不能早于起始行。")
        return cleaned


class AnnotationStatusForm(forms.Form):
    status = forms.ChoiceField(
        label="处理结果",
        choices=(
            (Annotation.Status.RESOLVED, "已处理"),
            (Annotation.Status.REJECTED, "驳回"),
        ),
    )
    resolution_note = forms.CharField(
        label="处理说明",
        min_length=1,
        widget=forms.Textarea(attrs={"rows": 2, "required": True}),
    )


class AnnotationReplyForm(forms.ModelForm):
    class Meta:
        model = AnnotationReply
        fields = ("body",)
        labels = {"body": "回复"}
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 2, "required": True, "placeholder": "写下回复…"}
            )
        }
