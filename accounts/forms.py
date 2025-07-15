# -*- coding: utf-8 -*-
# @File    : forms.py
# @Time    : 2025/7/11 12:03
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了accounts-forms功能的类和函数。
"""

# here put the import lib
from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(label="用户名")
    password = forms.CharField(label="口令", widget=forms.PasswordInput)
