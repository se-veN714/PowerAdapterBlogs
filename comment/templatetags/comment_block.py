# -*- coding: utf-8 -*-
# @File    : comment_block.py
# @Time    : 2025/7/2 02:57
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了自定义comment_block的类和函数。
"""

# here put the import lib
from django import template

from comment.form import CommentForm
from comment.models import Comment

register = template.Library()


@register.inclusion_tag('comment/form.html')
def form_block(target):
    print('target', target)
    return {
        'target': target,
        'comment_form': CommentForm(),
    }


@register.inclusion_tag('comment/list.html')
def list_block(target):
    return {
        'target': target,
        'comment_list': Comment.get_by_target(target),
    }
