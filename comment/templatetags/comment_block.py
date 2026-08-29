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


@register.inclusion_tag('pages/comment/form.html', takes_context=True)
def form_block(context, target):
    request = context["request"]
    profile = getattr(request.user, "profile", None)
    author_name = None
    author_avatar_url = ""
    if request.user.is_authenticated:
        author_name = (
            profile.public_name if profile is not None else request.user.username
        )
        if profile is not None and profile.is_public and profile.avatar:
            author_avatar_url = profile.avatar.url
    return {
        'target': target,
        'comment_form': CommentForm(),
        'request': request,
        'author_name': author_name,
        'author_avatar_url': author_avatar_url,
        'identity_verified': (
            request.user.is_authenticated
            and request.user.is_comment_identity_verified
        ),
    }


@register.inclusion_tag('pages/comment/list.html')
def list_block(target):
    return {
        'target': target,
        'comment_list': Comment.get_by_target(target),
    }
