from django import forms
from django.conf import settings

from boards.models import CodingProject, MusicScope, SkateClip, SkateClipMedia, SpotifyRecord


class SkateClipForm(forms.ModelForm):
    class Meta:
        model = SkateClip
        fields = (
            "homie",
            "order",
            "title",
            "category",
            "spot",
            "filmed_at",
            "duration",
            "status",
            "notes",
            "video_url",
            "thumbnail_url",
            "hud_type",
            "hud_label",
            "timecode",
            "is_public",
        )
        widgets = {
            "filmed_at": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }


class SkateClipMediaUploadForm(forms.Form):
    """私有原片上传表单（S1）。

    大小上限做快速失败；内容安全（容器/视频流/时长）由视图调用
    FFprobe 权威裁决，扩展名与 MIME 不参与判定。
    """

    source = forms.FileField(
        label="视频原片",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": "video/mp4,video/quicktime,video/webm,video/x-m4v,.mp4,.mov,.webm,.m4v",
                "data-skate-max-bytes": str(settings.SKATE_CLIP_MAX_UPLOAD_BYTES),
                "data-skate-max-duration-ms": str(settings.SKATE_CLIP_MAX_DURATION_MS),
            }
        ),
    )

    def clean_source(self):
        uploaded = self.cleaned_data["source"]
        if uploaded.size > settings.SKATE_CLIP_MAX_UPLOAD_BYTES:
            limit_mib = settings.SKATE_CLIP_MAX_UPLOAD_BYTES // (1024 * 1024)
            raise forms.ValidationError(
                f"文件超过大小上限（{limit_mib} MiB）。"
            )
        return uploaded


class MusicRecordForm(forms.ModelForm):
    class Meta:
        model = SpotifyRecord
        fields = (
            "title",
            "scope",
            "year",
            "month",
            "kind",
            "label",
            "value",
            "value2",
            "unit",
            "rank",
            "play_count",
            "minutes",
            "note",
            "cover",
            "external_url",
            "display_order",
        )
        widgets = {"note": forms.Textarea(attrs={"rows": 4})}

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get("scope")
        month = cleaned.get("month")
        kind = (cleaned.get("kind") or "").strip()
        if scope == MusicScope.MONTHLY and month is None:
            self.add_error("month", "月度记录必须填写月份。")
        if scope == MusicScope.YEARLY and month is not None:
            self.add_error("month", "年度记录不能填写月份。")
        if month is not None and not 1 <= month <= 12:
            self.add_error("month", "月份必须在 1 到 12 之间。")
        if kind in {"top_artist", "top_track"} and cleaned.get("rank") is None:
            self.add_error("rank", "排行记录必须填写排名。")
        return cleaned


class CodingProjectForm(forms.ModelForm):
    class Meta:
        model = CodingProject
        fields = (
            "index",
            "name",
            "description",
            "stack",
            "year",
            "status",
            "project_type",
            "repository_url",
            "demo_url",
            "cover",
            "is_featured",
            "is_active",
            "order",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def clean(self):
        cleaned = super().clean()
        project_type = cleaned.get("project_type")
        repository_url = cleaned.get("repository_url")
        demo_url = cleaned.get("demo_url")
        if project_type == CodingProject.ProjectType.GITHUB and not repository_url:
            self.add_error("repository_url", "GitHub 项目必须填写仓库链接。")
        if project_type == CodingProject.ProjectType.EXTERNAL and not demo_url:
            self.add_error("demo_url", "外部项目必须填写演示或项目链接。")
        return cleaned
