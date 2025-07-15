# -*- coding: utf-8 -*-
# @File    : md_latex.py
# @Time    : 2025/7/3 17:45
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了markdown+latex环境下功能的类和函数。
"""

# here put the import lib
import re
from html import escape


class LatexProcessor:
    """
    专门处理 Markdown 中的 LaTeX 内容的处理器
    确保数学公式中的特殊符号和换行符被正确处理
    """

    MATH_ENV_PATTERNS = [
        (r'\$(.*?)\$', 'inline'),  # 行内数学模式 $...$
        (r'\$\$(.*?)\$\$', 'block'),  # 块级数学模式 $$...$$
        (r'\\\((.*?)\\\)', 'inline'),  # \(...\)
        (r'\\\[(.*?)\\\]', 'block'),  # \[...\]
        (r'\\begin\{([a-z]+\*?)\}(.*?)\\end\{\1\}', 'environment')  # \begin{}...\end{}
    ]

    PLACEHOLDER_PREFIX = "%%LATEX_MATH_%%"

    def __init__(self, preserve_linebreaks=True, escape_html=False):
        """
        初始化处理器
        :param preserve_linebreaks: 是否保留 \\ 换行符
        :param escape_html: 是否转义 HTML 特殊字符
        """
        self.preserve_linebreaks = preserve_linebreaks
        self.escape_html = escape_html
        self.math_regions = {}
        self.counter = 0

    def protect_math_environments(self, text):
        """
        定位并保护所有数学环境
        """
        self.math_regions = {}
        self.counter = 0  # 重置计数器

        # 处理所有类型的数学环境
        for pattern, env_type in self.MATH_ENV_PATTERNS:
            pattern = re.compile(pattern, re.DOTALL)
            text = pattern.sub(self._create_protection_handler(env_type), text)

        return text

    def _create_protection_handler(self, env_type):
        """闭包函数捕获当前类的状态"""

        def handler(match):
            # 获取匹配内容
            if env_type == 'environment':
                env_name, content = match.group(1), match.group(2)
                raw_content = f"\\begin{{{env_name}}}{content}\\end{{{env_name}}}"
            else:
                content = match.group(1)
                delim = {
                    'inline': '$',
                    'block': '$$'
                }.get(env_type, '')
                raw_content = f"{delim}{content}{delim}"

            # 如果需要保留换行符
            if self.preserve_linebreaks:
                content = content.replace(r'\\', 'DOUBLE_BACKSLASH_PLACEHOLDER')

            # 递增计数器
            self.counter += 1
            placeholder = f"{self.PLACEHOLDER_PREFIX}{self.counter}%%"

            # 存储占位符信息
            self.math_regions[placeholder] = {
                'content': content,
                'type': env_type,
                'raw': raw_content
            }
            return placeholder

        return handler

    def restore_math_environments(self, text):
        """
        恢复被保护的数学环境
        """
        for placeholder, data in self.math_regions.items():
            if placeholder in text:
                content = data['content']

                # 恢复换行符
                if self.preserve_linebreaks:
                    content = content.replace('DOUBLE_BACKSLASH_PLACEHOLDER', r'\\')

                # HTML 转义
                if self.escape_html:
                    content = escape(content)

                text = text.replace(placeholder, data['raw'].replace(data['content'], content))

        return text
