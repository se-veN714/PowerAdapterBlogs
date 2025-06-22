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


class CommentForm(forms.ModelForm):
    nickname = forms.CharField(label='昵称',max_length=50,)
    email = forms.EmailField(label='E-mail',max_length=50,)
    website = forms.URLField(label='网站',max_length=100,)
    content = forms.CharField(label='内容',max_length=500,)

    def clean_content(self):
        content = self.cleaned_data['content']
        if len(content) < 10:
            raise forms.ValidationError('输入字符长度不能小于10')
        return content

    class Meta:
        model = Comment
        fields = ('nickname', 'email', 'website', 'content')
