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

from Blogs.models import Post


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
        queryset=Post.objects.none(),  # 后面替换为你的 Tag 模型的 queryset
        widget=forms.CheckboxSelectMultiple(),  # 可改成 Select2 或其他组件
        label='标签',
        required=False,
    )

    class Meta:
        model = Post
        fields = ['title', 'cover', 'desc', 'content', 'category', 'tag']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Tag, Category  # 防止循环导入
        self.fields['tag'].queryset = Tag.objects.all()
        self.fields['category'].queryset = Category.objects.all()
