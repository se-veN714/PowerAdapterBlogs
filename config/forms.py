from urllib.parse import urlsplit

from django import forms

from .models import ContentReport


class ContentReportForm(forms.ModelForm):
    class Meta:
        model = ContentReport
        fields = ("category", "target_path", "description", "contact_email")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 7}),
        }

    def clean_target_path(self):
        value = self.cleaned_data["target_path"].strip()
        if not value:
            return ""
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or not value.startswith("/"):
            raise forms.ValidationError("仅接受本站路径，例如 /Blogs/post/example/。")
        if value.startswith("//"):
            raise forms.ValidationError("仅接受本站路径，例如 /Blogs/post/example/。")
        return value

    def clean_description(self):
        value = self.cleaned_data["description"].strip()
        if len(value) < 10:
            raise forms.ValidationError("请至少填写 10 个字符，说明需要核查的问题。")
        return value
