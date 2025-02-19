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
from django import forms


class PostAdminForm(forms.ModelForm):
    desc = forms.CharField(widget=forms.Textarea, label='摘要', required=False)
