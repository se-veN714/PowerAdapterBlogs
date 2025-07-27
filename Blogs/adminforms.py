# -*- coding: utf-8 -*-
# @File    : adminforms.py
# @Time    : 2025/2/20 01:35
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了AdminForm自定义的类和函数。
"""

# here put the import lib
from dal import autocomplete
from django import forms

from Blogs.models import Category, Tag, Post


class PostAdminForm(forms.ModelForm):
    desc = forms.CharField(widget=forms.Textarea, label="摘要", required=False)
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        widget=autocomplete.ModelSelect2(url="category-autocomplete"),
        label="分类"
    )
    tag = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.all(),
        widget=autocomplete.ModelSelect2Multiple(url="tag-autocomplete"),
        label="标签"
    )

    class Meta:
        model = Post
        fields = ["category", "tag", "title", "desc", "content", "status"]
