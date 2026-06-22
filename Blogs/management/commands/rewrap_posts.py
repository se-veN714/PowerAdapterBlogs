"""对指定文章的正文内容执行单词边界换行（_word_wrap）。

用途：
    - 文章编辑后内容过长时，可批量执行分行处理
    - 可在 dashboard admin action 中调用，也可 CLI 手动运行

用法：
    python manage.py rewrap_posts --post-ids 1,2,3        # 指定文章 ID
    python manage.py rewrap_posts --all                   # 全部正常文章
    python manage.py rewrap_posts --all --dry-run         # 预览模式
"""

import logging

from django.core.management.base import BaseCommand

from Blogs.models import Post
from Blogs.revisions import _word_wrap

logger = logging.getLogger(__name__)


def apply_word_wrap_to_post(post, editor=None):
    """对单篇文章的 content 字段执行 _word_wrap 处理。

    Args:
        post: Post 实例。
        editor: 编辑者 (User)，提供时会自动创建修订快照。

    Returns:
        (original_length, wrapped_length) 或 None（无需处理时）。
    """
    original = post.content
    wrapped = _word_wrap(original)

    if wrapped == original:
        return None  # 无变化，跳过

    post.content = wrapped
    post.save(update_fields=['content'])

    # 内容变更后创建修订快照（确保 diff 可追踪）
    if editor:
        from Blogs.revisions import create_revision
        create_revision(post, editor, change_type='minor',
                        edit_summary='自动分行处理（word-wrap）')

    return len(original), len(wrapped)


def apply_word_wrap_to_queryset(queryset, stdout=None, style=None, dry_run=False, editor=None):
    """对 Post 查询集批量执行 word wrap。

    Args:
        queryset: Post QuerySet。
        stdout: Django stdout 句柄（可选，用于管理命令输出）。
        style: Django style 句柄（可选）。
        dry_run: True 时仅预览不写入。
        editor: 编辑者 User（可选），提供时会为每篇变更创建修订快照。

    Returns:
        dict: 包含 success, skipped, failed 计数的结果。
    """
    result = {'success': 0, 'skipped': 0, 'failed': 0}

    for post in queryset:
        try:
            outcome = apply_word_wrap_to_post(post, editor=editor)
            if outcome is None:
                result['skipped'] += 1
                if stdout and not dry_run:
                    stdout.write(f'  跳过 #{post.id} "{post.title[:30]}" (无需分行)')
            else:
                orig_len, new_len = outcome
                result['success'] += 1
                if stdout:
                    stdout.write(
                        f'  ✅ #{post.id} "{post.title[:30]}" '
                        f'{orig_len} → {new_len} 字符'
                    )
        except Exception:
            result['failed'] += 1
            logger.exception(f"rewrap_posts 失败: post_id={post.id}")
            if stdout:
                stdout.write(
                    style.ERROR(f'  ❌ #{post.id} "{post.title[:30]}" 处理失败')
                )

    return result


class Command(BaseCommand):
    """批量文章分行管理命令。"""

    help = "对文章的正文内容执行单词边界换行（_word_wrap）"

    def add_arguments(self, parser):
        parser.add_argument(
            '--post-ids', type=str, default='',
            help='逗号分隔的文章 ID 列表（如 "1,3,5"）',
        )
        parser.add_argument(
            '--all', action='store_true', default=False,
            help='处理全部正常状态文章',
        )
        parser.add_argument(
            '--dry-run', action='store_true', default=False,
            help='预览模式，不实际写入',
        )

    def handle(self, *args, **options):
        post_ids_str = options['post_ids']
        all_posts = options['all']
        dry_run = options['dry_run']

        if not post_ids_str and not all_posts:
            self.stdout.write(
                self.style.ERROR('请指定 --post-ids 或 --all')
            )
            return

        if post_ids_str:
            try:
                ids = [int(x.strip()) for x in post_ids_str.split(',') if x.strip()]
            except ValueError:
                self.stdout.write(self.style.ERROR('--post-ids 格式错误，示例: 1,2,3'))
                return
            queryset = Post.objects.filter(id__in=ids)
        else:
            queryset = Post.objects.filter(status=Post.STATUS_NORMAL)

        count = queryset.count()
        self.stdout.write(f'\n{"[预览] " if dry_run else ""}'
                          f'共 {count} 篇文章待处理\n')

        if dry_run:
            for post in queryset:
                wrapped = _word_wrap(post.content)
                if wrapped != post.content:
                    self.stdout.write(
                        f'  需分行: #{post.id} "{post.title[:30]}" '
                        f'({len(post.content)} → {len(wrapped)} 字符)'
                    )
            self.stdout.write(
                self.style.WARNING('\n[--dry-run] 以上为预览，未实际写入')
            )
            return

        result = apply_word_wrap_to_queryset(
            queryset, stdout=self.stdout, style=self.style,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'\n处理完成: 成功 {result["success"]} / '
                f'跳过 {result["skipped"]} / '
                f'失败 {result["failed"]}'
            )
        )
