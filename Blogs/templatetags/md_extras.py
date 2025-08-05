# -*- coding: utf-8 -*-
# @File    : md_extras.py
# @Time    : 2025/7/3 01:41
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了Markdown文件支持功能的类和函数。
"""
# here put the import lib

import markdown as md_lib
from django import template
from django.utils.safestring import mark_safe
from markdown.extensions.toc import TocExtension, slugify_unicode

from Blogs.blog_utils.md_latex import LatexProcessor

register = template.Library()
lp = LatexProcessor()


@register.filter
def markdown_to_html(value):

    md = md_lib.Markdown(
        extensions=[
            'extra',
            'fenced_code',
            'tables',
            'footnotes',
            TocExtension(slugify=slugify_unicode,toc_class='toc menu'),
        ]
    )

    lp_value = lp.protect_math_environments(value)
    md_value = md.convert(lp_value)
    html = lp.restore_math_environments(md_value)

    register.md_instance = md

    return mark_safe(html)

@register.simple_tag()
def render_toc():
    try:
        return mark_safe(register.md_instance.toc)
    except AttributeError:
        return ''