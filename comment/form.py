# -*- coding: utf-8 -*-
# @File    : form.py
# @Time    : 2025/6/23 02:22
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了 Form 功能的类和函数。
"""

# here put the import lib
from django import forms

from comment.models import Comment
import markdown


class CommentForm(forms.ModelForm):
    nickname = forms.CharField(
        label='昵称',
        max_length=50,
        required=False,  # 匿名时可留空
        widget=forms.TextInput(attrs={
            'class': 'input',
            'placeholder': '昵称（可选）'
        })
    )
    content = forms.CharField(
        label='内容',
        max_length=500,
        widget=forms.Textarea(attrs={
            'class': 'textarea',
            'placeholder': '请输入评论内容',
            'rows': 4
        })
    )

    def clean_content(self):
        content = self.cleaned_data['content'].rstrip()
        if len(content.strip()) < 10:
            raise forms.ValidationError('输入字符长度不能小于10')

        content = markdown.markdown(content)
        return content


    class Meta:
        model = Comment
        fields = ('nickname', 'content')
