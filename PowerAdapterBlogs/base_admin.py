# -*- coding: utf-8 -*-
# @File    : base_admin.py
# @Time    : 2025/2/20 02:18
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了基本用户owner字段功能的类和函数。
"""

# here put the import lib
from django.contrib import admin


class BaseOwnerAdmin(admin.ModelAdmin):
    """
    1. 用于补充文章、分类、标签、侧边栏、友链这些 Model 的 owner 字段
    2. 用于针对 queryset 过滤当前用户的数据
    """

    def get_queryset(self, request):
        qs = super(BaseOwnerAdmin, self).get_queryset(request)
        return qs.filter(owner=request.user)

    def save_model(self, request, obj, form, change):
        obj.owner = request.user
        return super(BaseOwnerAdmin, self).save_model(request, obj, form, change)

