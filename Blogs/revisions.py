# -*- coding: utf-8 -*-
"""
文章修订追踪 — 工具模块

提供版本号计算、快照创建等纯函数，供 views.py 调用。
"""

import difflib
import logging
import re
from django.db.models import Model

logger = logging.getLogger(__name__)

# Markdown 结构型行的正则：标题、代码围栏、表格、水平线、引用、admonition
_STRUCTURAL_LINE_RE = re.compile(
    r'^(\s{0,3}#|'          # 标题（含 ATX 和 setext）
    r'\s{0,3}```|'          # 代码围栏起止
    r'\s{0,3}\|.*\|'        # 表格行
    r'|^\s{0,3}([-*_]{3,})\s*$|'  # 水平线
    r'^\s{0,3}>|'           # 引用
    r'^\s{0,3}\|)'          # 表格（续）
)


def get_next_version(post, change_type: str) -> tuple[int, int]:
    """根据变更类型计算下一个版本号 (major, minor)

    :param post: Post 实例
    :param change_type: 'major' 或 'minor'
    :return: (major, minor)
    """
    last = post.revisions.order_by('-major', '-minor').first()
    if not last:
        return (1, 0)  # 首版 v1.0

    if change_type == 'major':
        return (last.major + 1, 0)   # v1.3 → v2.0
    else:
        return (last.major, last.minor + 1)  # v1.3 → v1.4


def create_revision(post, editor, change_type: str = 'minor',
                    edit_summary: str = '') -> Model:
    """为指定文章创建修订快照（含预计算 diff）

    :param post: Post 实例（已保存）
    :param editor: User 实例
    :param change_type: 'major' | 'minor'
    :param edit_summary: 编辑摘要
    :return: PostRevision 实例
    """
    from .models import PostRevision

    major, minor = get_next_version(post, change_type)
    new_version = f"{major}.{minor}"

    # 预计算与前一个版本的 diff（写时计算，读时零成本）
    diff_html = None
    previous = post.revisions.order_by('-major', '-minor').first()
    if previous:
        diff_html = render_diff(
            previous.content, post.content,
            previous.version, new_version,
        )

    revision = PostRevision.objects.create(
        post=post,
        major=major, minor=minor,  # version 在 save() 中自动生成
        title=post.title,
        desc=post.desc,
        content=post.content,
        slug=post.slug,
        editor=editor,
        change_type=change_type,
        edit_summary=edit_summary,
        diff_from_previous=diff_html,
    )
    logger.info(f"PostRevision 创建: post_id={post.id} version=v{revision.version} "
                f"change_type={change_type} editor_id={editor.id} "
                f"diff_stored={'yes' if diff_html else 'no'}")
    return revision


def _word_wrap(text: str, width: int = 80) -> str:
    """按单词边界对文本换行，提升行级 diff 颗粒度。

    规律：
    - Markdown 结构型行（标题、代码围栏、表格、引用等）保持原样不换行
    - 普通段落按 width 个字符在单词边界处强制换行
    - 空行保留，维持段落分隔
    """
    lines = text.splitlines()
    result = []
    for line in lines:
        stripped = line.strip()

        # 结构型行 → 原样保留
        if (not stripped
                or stripped.startswith('#')
                or stripped.startswith('```')
                or stripped.startswith('|')
                or stripped.startswith('>')
                or stripped.startswith('!!!')
                or (stripped.startswith(('- ', '* ', '+ ')) and len(stripped) < width)
                or re.match(r'^\s{0,3}([-*_]{3,})\s*$', stripped)
                or re.match(r'^(\d{1,2}\.\s)', stripped) and len(stripped) < width):
            result.append(line)
            continue

        # 普通文本行 → 单词边界换行
        words = line.split()
        wrapped_line = ''
        for word in words:
            if wrapped_line and len(wrapped_line) + 1 + len(word) > width:
                result.append(wrapped_line)
                wrapped_line = word
            else:
                wrapped_line = (wrapped_line + ' ' + word) if wrapped_line else word
        if wrapped_line:
            result.append(wrapped_line)

    return '\n'.join(result)


def render_diff(old_text: str, new_text: str, from_ver: str, to_ver: str,
                line_width: int = 80) -> str:
    """生成 HTML 格式 side-by-side diff

    先对内容做单词边界换行预处理，再使用 difflib.HtmlDiff 做行级对比。
    这样一篇文章的每个段落会被拆成多行，只有真正变更的行才会出现在 diff 中。
    """
    wrapped_old = _word_wrap(old_text, line_width)
    wrapped_new = _word_wrap(new_text, line_width)

    differ = difflib.HtmlDiff(tabsize=4, wrapcolumn=line_width)
    return differ.make_table(
        wrapped_old.splitlines(),
        wrapped_new.splitlines(),
        fromdesc=f'v{from_ver}',
        todesc=f'v{to_ver}',
        context=True,
        numlines=1,  # 上下文 1 行即可，换行后颗粒度已经够细
    )


def can_view_staff_only(user) -> bool:
    """判断用户是否可以查看 VISIBILITY_STAFF_ONLY 的文章"""
    if not user or not user.is_authenticated:
        return False
    return user.is_staff or user.is_dashboard_user
