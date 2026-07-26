# -*- coding: utf-8 -*-
# @File    : forms.py
# @Time    : 2025/8/4 03:03
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了Blogs-forms功能的类和函数。
"""

# here put the import lib
# forms.py
from django import forms
from django.templatetags.static import static

from Blogs.models import Category, Post, Tag
from Blogs.image_validation import validate_uploaded_image
from boards.policies import categories_for_post_creation


class PostForm(forms.ModelForm):
    title = forms.CharField(
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': '标题',
                'rows': '1'
            }, ),
    )

    desc = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'placeholder': '摘要',
                'rows': '5'
            }
        )
    )

    cover = forms.ImageField(
        required=False,
        label='封面',
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
        }),
    )

    content = forms.CharField(
        label='正文',
        widget=forms.HiddenInput()  # 内容用 Toast UI Editor 渲染，前端填充这个字段
    )

    category = forms.Select(
        attrs={
            'class': 'form-select',
        }
    )

    tag = forms.ModelMultipleChoiceField(
        queryset=Post.objects.none(),
        widget=forms.CheckboxSelectMultiple(),
        label='标签',
        required=False,
    )

    visibility = forms.TypedChoiceField(
        choices=(
            (Post.VISIBILITY_PUBLIC, '公开'),
            (Post.VISIBILITY_STAFF_ONLY, '仅本板块成员可见'),
        ),
        coerce=int,
        initial=Post.VISIBILITY_PUBLIC,
        label='可见性',
        help_text='公开文章所有访客可见；板块内文章仅授权成员可见。',
        error_messages={'required': '请选择文章可见性。'},
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    # === PostRevision 相关（非 Post 模型字段，在视图 form_valid 中消费） ===
    change_type = forms.ChoiceField(
        choices=[('major', '大版本'), ('minor', '小修订')],
        initial='minor',
        label='变更类型',
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False,  # 创建时可选（默认 minor）
    )
    edit_summary = forms.CharField(
        max_length=200,
        required=False,
        label='编辑摘要',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '简述本次修改'}),
    )
    base_revision_id = forms.IntegerField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Post
        fields = ['title', 'cover', 'desc', 'content', 'category', 'tag', 'visibility']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tag'].queryset = Tag.objects.all()
        self.fields['category'].queryset = categories_for_post_creation(
            user,
            Category.objects.all(),
        )
        self.category_cover_map = {
            str(category.pk): static(category.default_cover_static_path)
            for category in self.fields['category'].queryset
        }
        if not self.is_bound and self.instance.pk:
            self.initial['base_revision_id'] = (
                self.instance.revisions.order_by('-major', '-minor')
                .values_list('pk', flat=True)
                .first()
            )

    def clean_cover(self):
        cover = self.cleaned_data.get('cover')
        if cover:
            validate_uploaded_image(cover)
        return cover
