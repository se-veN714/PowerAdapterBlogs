# -*- coding: utf-8 -*-
"""
文章修订追踪 — 工具模块

提供版本号计算、快照创建等纯函数，供 views.py 调用。
"""

import difflib
import logging
import re
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Model
from django.utils.html import escape
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

DIFF_SCHEMA_VERSION = 1
DIFF_ALGORITHM = 'markdown-block-sentence-char-v1'
CHAR_DIFF_MAX_INPUT = 20_000

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


@transaction.atomic
def create_revision(post, editor, change_type: str = 'minor',
                    edit_summary: str = '') -> Model:
    """为指定文章创建修订快照（含预计算 diff）

    :param post: Post 实例（已保存）
    :param editor: User 实例
    :param change_type: 'major' | 'minor'
    :param edit_summary: 编辑摘要
    :return: PostRevision 实例
    """
    from .models import Post, PostRevision

    if change_type not in {'major', 'minor'}:
        raise ValidationError({'change_type': '不支持的修订类型。'})

    # 版本号分配属于 Post 聚合的一部分。锁住父记录后，同一文章的并发
    # 修订会串行执行，避免两个请求读取到相同的“最后版本”。
    locked_post = Post.objects.select_for_update().get(pk=post.pk)

    major, minor = get_next_version(locked_post, change_type)
    new_version = f"{major}.{minor}"

    # 兼容期双写：旧 HTML 供历史模板兜底，结构化数据负责新展示。
    diff_html = None
    diff_structured = None
    diff_stats = {}
    previous = locked_post.revisions.order_by('-major', '-minor').first()
    if previous:
        diff_html = render_diff(
            previous.content, locked_post.content,
            previous.version, new_version,
        )
        diff_structured = build_structured_diff(
            previous.content,
            locked_post.content,
            previous.version,
            new_version,
        )
        diff_stats = diff_structured['stats']

    revision = PostRevision.objects.create(
        post=locked_post,
        major=major, minor=minor,  # version 在 save() 中自动生成
        title=locked_post.title,
        desc=locked_post.desc,
        content=locked_post.content,
        slug=locked_post.slug,
        editor=editor,
        change_type=change_type,
        edit_summary=edit_summary,
        diff_from_previous=diff_html,
        diff_structured=diff_structured,
        diff_algorithm=DIFF_ALGORITHM if diff_structured else '',
        diff_stats=diff_stats,
    )
    logger.info(f"PostRevision 创建: post_id={locked_post.id} version=v{revision.version} "
                f"change_type={change_type} editor_id={getattr(editor, 'id', None)} "
                f"diff_stored={'yes' if diff_html else 'no'}")
    return revision


def _block_kind(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith('#'):
        return 'heading'
    if stripped.startswith(('```', '~~~')):
        return 'code'
    if stripped.startswith('|'):
        return 'table'
    if stripped.startswith('>'):
        return 'quote'
    if re.match(r'(?:[-*+] |\d{1,3}\. )', stripped):
        return 'list'
    if re.match(r'[-*_]{3,}\s*$', stripped):
        return 'separator'
    return 'paragraph'


def _markdown_blocks(text: str) -> list[dict[str, str]]:
    """Split Markdown into stable semantic blocks without parsing its HTML."""
    blocks = []
    paragraph = []
    code = []
    fence = None

    def flush_paragraph():
        if paragraph:
            blocks.append({'kind': 'paragraph', 'text': '\n'.join(paragraph)})
            paragraph.clear()

    for line in text.splitlines():
        stripped = line.lstrip()
        fence_marker = stripped[:3] if stripped.startswith(('```', '~~~')) else None
        if fence:
            code.append(line)
            if fence_marker == fence:
                blocks.append({'kind': 'code', 'text': '\n'.join(code)})
                code.clear()
                fence = None
            continue
        if fence_marker:
            flush_paragraph()
            fence = fence_marker
            code.append(line)
            continue
        if not stripped:
            flush_paragraph()
            continue

        kind = _block_kind(line)
        if kind == 'paragraph':
            paragraph.append(line)
        else:
            flush_paragraph()
            blocks.append({'kind': kind, 'text': line})

    flush_paragraph()
    if code:
        blocks.append({'kind': 'code', 'text': '\n'.join(code)})
    return blocks


def _sentence_units(text: str) -> list[str]:
    """Keep Chinese and English sentence punctuation attached to each unit."""
    return [part for part in re.split(r'(?<=[。！？!?；;\.])(?=\s|[^\s])|(?<=\n)', text)
            if part]


def _char_segments(old_text: str, new_text: str) -> list[dict[str, str]]:
    if len(old_text) + len(new_text) > CHAR_DIFF_MAX_INPUT:
        return [{
            'op': 'replace',
            'old_text': old_text,
            'new_text': new_text,
        }]
    segments = []
    matcher = difflib.SequenceMatcher(None, old_text, new_text, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        segments.append({
            'op': tag,
            'old_text': old_text[i1:i2],
            'new_text': new_text[j1:j2],
        })
    return segments


def _inline_segments(old_text: str, new_text: str) -> list[dict[str, str]]:
    """Align sentences first, then use character granularity inside replacements."""
    old_sentences = _sentence_units(old_text)
    new_sentences = _sentence_units(new_text)
    matcher = difflib.SequenceMatcher(None, old_sentences, new_sentences, autojunk=False)
    segments = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_part = ''.join(old_sentences[i1:i2])
        new_part = ''.join(new_sentences[j1:j2])
        if tag == 'replace':
            segments.extend(_char_segments(old_part, new_part))
        else:
            segments.append({'op': tag, 'old_text': old_part, 'new_text': new_part})
    return segments


def build_structured_diff(old_text: str, new_text: str, from_ver: str,
                          to_ver: str) -> dict:
    """Build a JSON-safe Markdown block/sentence/character diff contract."""
    old_blocks = _markdown_blocks(old_text)
    new_blocks = _markdown_blocks(new_text)
    old_keys = [(block['kind'], block['text']) for block in old_blocks]
    new_keys = [(block['kind'], block['text']) for block in new_blocks]
    matcher = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    blocks = []
    stats = {
        'added_blocks': 0,
        'deleted_blocks': 0,
        'changed_blocks': 0,
        'inserted_chars': 0,
        'deleted_chars': 0,
    }

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        old_slice = old_blocks[i1:i2]
        new_slice = new_blocks[j1:j2]
        old_value = '\n\n'.join(block['text'] for block in old_slice)
        new_value = '\n\n'.join(block['text'] for block in new_slice)
        segments = _inline_segments(old_value, new_value)
        blocks.append({
            'op': tag,
            'old_kind': old_slice[0]['kind'] if old_slice else None,
            'new_kind': new_slice[0]['kind'] if new_slice else None,
            'segments': segments,
        })
        stats['added_blocks'] += len(new_slice) if tag == 'insert' else 0
        stats['deleted_blocks'] += len(old_slice) if tag == 'delete' else 0
        stats['changed_blocks'] += max(len(old_slice), len(new_slice)) if tag == 'replace' else 0
        for segment in segments:
            if segment['op'] in {'insert', 'replace'}:
                stats['inserted_chars'] += len(segment['new_text'])
            if segment['op'] in {'delete', 'replace'}:
                stats['deleted_chars'] += len(segment['old_text'])

    return {
        'schema_version': DIFF_SCHEMA_VERSION,
        'algorithm': DIFF_ALGORITHM,
        'from_version': str(from_ver),
        'to_version': str(to_ver),
        'blocks': blocks,
        'stats': stats,
    }


def render_structured_diff(diff_data: dict, mode: str = 'split') -> str:
    """Render supported structured data to escaped HTML in an R4 view mode."""
    if (not isinstance(diff_data, dict)
            or diff_data.get('schema_version') != DIFF_SCHEMA_VERSION
            or diff_data.get('algorithm') != DIFF_ALGORITHM):
        raise ValueError('不支持的结构化 Diff 版本。')
    if mode not in {'split', 'inline', 'stats'}:
        raise ValueError('不支持的 Diff 展示模式。')

    stats = diff_data.get('stats') or {}
    parts = [
        f'<div class="structured-diff structured-diff-{mode}">',
        '<div class="structured-diff-stats">',
        f'<span>+{int(stats.get("added_blocks", 0))} 块</span>',
        f'<span>-{int(stats.get("deleted_blocks", 0))} 块</span>',
        f'<span>~{int(stats.get("changed_blocks", 0))} 块</span>',
        f'<span>+{int(stats.get("inserted_chars", 0))} 字符</span>',
        f'<span>-{int(stats.get("deleted_chars", 0))} 字符</span>',
        '</div>',
    ]
    if mode == 'stats':
        if not diff_data.get('blocks'):
            parts.append('<p class="structured-diff-empty">正文内容没有变化。</p>')
        parts.append('</div>')
        return mark_safe(''.join(parts))

    for block in diff_data.get('blocks') or []:
        if mode == 'inline':
            inline_parts = []
            for segment in block.get('segments') or []:
                op = segment.get('op', 'equal')
                old_value = escape(str(segment.get('old_text', '')))
                new_value = escape(str(segment.get('new_text', '')))
                if op == 'equal':
                    inline_parts.append(f'<span>{new_value or old_value}</span>')
                elif op == 'delete':
                    inline_parts.append(f'<del class="diff-delete">{old_value}</del>')
                elif op == 'insert':
                    inline_parts.append(f'<ins class="diff-insert">{new_value}</ins>')
                else:
                    inline_parts.append(f'<del class="diff-delete">{old_value}</del>')
                    inline_parts.append(f'<ins class="diff-insert">{new_value}</ins>')
            parts.extend([
                f'<section class="structured-diff-block" data-op="{escape(str(block.get("op", "replace")))}">',
                '<pre class="structured-diff-inline-content">',
                ''.join(inline_parts),
                '</pre></section>',
            ])
            continue

        old_parts = []
        new_parts = []
        for segment in block.get('segments') or []:
            op = segment.get('op', 'equal')
            old_value = escape(str(segment.get('old_text', '')))
            new_value = escape(str(segment.get('new_text', '')))
            old_parts.append(f'<span class="diff-{op}">{old_value}</span>')
            new_parts.append(f'<span class="diff-{op}">{new_value}</span>')
        parts.extend([
            f'<section class="structured-diff-block" data-op="{escape(str(block.get("op", "replace")))}">',
            '<pre class="structured-diff-old">', ''.join(old_parts), '</pre>',
            '<pre class="structured-diff-new">', ''.join(new_parts), '</pre>',
            '</section>',
        ])
    if not diff_data.get('blocks'):
        parts.append('<p class="structured-diff-empty">正文内容没有变化。</p>')
    parts.append('</div>')
    return mark_safe(''.join(parts))


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
