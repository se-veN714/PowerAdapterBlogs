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
from django import template
from django.utils.safestring import mark_safe

import mistune
from blog_utils.md_latex import LatexProcessor

register = template.Library()
lp = LatexProcessor()

@register.filter
def markdown_to_html(value):
    markdown = mistune.create_markdown(
        plugins=['strikethrough', 'footnotes', 'table', 'url'],
        escape=False,
    )
    lp_value = lp.protect_math_environments(value)
    md_value = markdown(lp_value)
    html = lp.restore_math_environments(md_value)
    print("======== 渲染后的 HTML ========")
    print(html)
    print("======== 原始 Markdown ========")
    print(value)

    return mark_safe(html)
