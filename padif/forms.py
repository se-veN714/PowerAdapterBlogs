from typing import Any

from django import forms

from .models import Document, Version


class DocumentUploadForm(forms.Form):
    title = forms.CharField(label="标题", max_length=200, required=False)
    markdown_file = forms.FileField(label="Markdown 文件")
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
    markdown_file = forms.FileField(label="Markdown 文件")
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
