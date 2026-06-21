# -*- coding: utf-8 -*-
"""
文章修订追踪 — 工具模块

提供版本号计算、快照创建等纯函数，供 views.py 调用。
"""

import difflib
import logging
from typing import Optional

from django.db.models import Model

logger = logging.getLogger(__name__)


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
    """为指定文章创建修订快照

    :param post: Post 实例（已保存）
    :param editor: User 实例
    :param change_type: 'major' | 'minor'
    :param edit_summary: 编辑摘要
    :return: PostRevision 实例
    """
    from .models import PostRevision

    major, minor = get_next_version(post, change_type)
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
    )
    logger.info(f"PostRevision 创建: post_id={post.id} version=v{revision.version} "
                f"change_type={change_type} editor_id={editor.id}")
    return revision


def render_diff(old_text: str, new_text: str, from_ver: str, to_ver: str) -> str:
    """生成 HTML 格式 side-by-side diff

    使用 difflib.HtmlDiff（Python 标准库，零依赖）
    """
    differ = difflib.HtmlDiff(tabsize=4, wrapcolumn=80)
    return differ.make_table(
        old_text.splitlines(),
        new_text.splitlines(),
        fromdesc=f'v{from_ver}',
        todesc=f'v{to_ver}',
        context=True,
        numlines=3,
    )


def can_view_staff_only(user) -> bool:
    """判断用户是否可以查看 VISIBILITY_STAFF_ONLY 的文章"""
    if not user or not user.is_authenticated:
        return False
    return user.is_staff or user.is_dashboard_user
