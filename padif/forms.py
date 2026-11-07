from typing import Any

from django import forms
from django.db.models import F, Max
from django.db.models.functions import Coalesce

from .models import Annotation, AnnotationReply, Branch, Document, Version


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


class BranchCommitFields(forms.Form):
    branch_id = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)
    base_version_id = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)


class VersionCommitForm(BranchCommitFields):
    content = forms.CharField(label="正文", widget=forms.Textarea)
    commit_message = forms.CharField(label="本次修改", max_length=300)
    version_kind = forms.ChoiceField(label="版本级别", choices=Version.Kind.choices)


class VersionUploadForm(BranchCommitFields):
    target_branch = forms.ModelChoiceField(label="目标分支", queryset=Branch.objects.none(), required=False, empty_label=None)
    branch_bases = forms.JSONField(required=False, widget=forms.HiddenInput)
    markdown_file = forms.FileField(
        label="Markdown 文件",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".md,.markdown,text/markdown"}
        ),
    )
    commit_message = forms.CharField(label="本次修改", max_length=300)
    version_kind = forms.ChoiceField(label="版本级别", choices=Version.Kind.choices)

    def __init__(self, *args, document=None, **kwargs):
        super().__init__(*args, **kwargs)
        if document is not None:
            branches = document.branches.filter(archived_at__isnull=True).annotate(
                head_id=Coalesce(Max("versions__id"), F("forked_from_id")),
            )
            self.fields["target_branch"].queryset = branches
            # Carry the heads seen when the form was rendered, including without JS.
            self.initial.setdefault("branch_bases", {str(item.pk): item.head_id for item in branches})
            self.initial.setdefault("target_branch", self.initial.get("branch_id"))

    def clean(self):
        cleaned = super().clean()
        target = cleaned.get("target_branch")
        if target is not None:
            bases = cleaned.get("branch_bases")
            expected = bases.get(str(target.pk)) if isinstance(bases, dict) else None
            if type(expected) is not int or expected < 1:
                raise forms.ValidationError("目标分支基准缺失，请刷新页面后重新选择文件。")
            cleaned["base_version_id"] = expected
        return cleaned


class BranchCreateForm(forms.Form):
    name = forms.RegexField(regex=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64, label="分支名")
    description = forms.CharField(max_length=300, required=False, label="说明")
    fork_from_version_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class BranchPublishForm(forms.Form):
    commit_message = forms.CharField(max_length=300, label="发布说明")
    version_kind = forms.ChoiceField(choices=Version.Kind.choices, initial="patch", label="版本级别")
    base_version_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    source_version_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    confirm_replace = forms.BooleanField(label="我已审阅差异，确认主线正文采用分支整稿")


class VersionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"v{obj.semantic_version} · {obj.branch.name}"


class DiffSelectionForm(forms.Form):
    from_version = VersionChoiceField(label="旧版本", queryset=Version.objects.none())
    to_version = VersionChoiceField(label="新版本", queryset=Version.objects.none())
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
        versions = document.versions.select_related("created_by", "branch").all()
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
