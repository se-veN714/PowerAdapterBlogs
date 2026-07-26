"""
回填 PostRevision 的旧 HTML 与 R3 结构化 Diff（迁移前创建的 revision）
用法：python manage.py backfill_diffs [--limit N] [--dry-run]
"""
import logging

from django.core.management.base import BaseCommand
from django.db import models

from Blogs.models import PostRevision
from Blogs.revisions import DIFF_ALGORITHM, build_structured_diff, render_diff

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '回填已有 PostRevision 的 HTML 与结构化 Diff 字段'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0,
                            help='仅处理最近 N 条 revision（0=全部）')
        parser.add_argument('--dry-run', action='store_true',
                            help='仅检查，不写入')
        parser.add_argument('--force', action='store_true',
                            help='强制重新计算已有 HTML 与结构化 diff')

    def handle(self, *args, **options):
        limit = options['limit']
        dry_run = options['dry_run']
        force = options['force']

        qs = PostRevision.objects.order_by('-major', '-minor')
        if limit:
            qs = qs[:limit]

        total = qs.count()
        updated = 0
        skipped = 0
        overwritten = 0

        self.stdout.write(f'共 {total} 条 revision 待检查...')

        for rev in qs:
            if rev.diff_from_previous and rev.diff_structured and not force:
                skipped += 1
                continue
            if (rev.diff_from_previous or rev.diff_structured) and force:
                overwritten += 1

            # 找到该 post 的前一个版本（按 major.minor 降序，比当前版本小的第一个）
            prev = PostRevision.objects.filter(
                post=rev.post
            ).filter(
                # major 更小，或 major 相同但 minor 更小
                models.Q(major__lt=rev.major) |
                models.Q(major=rev.major, minor__lt=rev.minor)
            ).order_by('-major', '-minor').first()

            if not prev:
                # v1.0 没有前驱
                skipped += 1
                continue

            diff_html = rev.diff_from_previous
            if force or not diff_html:
                diff_html = render_diff(
                    prev.content, rev.content, prev.version, rev.version,
                )
            diff_structured = build_structured_diff(
                prev.content, rev.content, prev.version, rev.version,
            )
            if dry_run:
                self.stdout.write(
                    f'  [DRY-RUN] {rev} ← {prev}  '
                    f'diff_len={len(diff_html)} blocks={len(diff_structured["blocks"])}'
                )
            else:
                rev.diff_from_previous = diff_html
                rev.diff_structured = diff_structured
                rev.diff_algorithm = DIFF_ALGORITHM
                rev.diff_stats = diff_structured['stats']
                rev.save(update_fields=[
                    'diff_from_previous',
                    'diff_structured',
                    'diff_algorithm',
                    'diff_stats',
                ])
                self.stdout.write(
                    f'  [OK] {rev} ← {prev}  '
                    f'diff_len={len(diff_html)} blocks={len(diff_structured["blocks"])}'
                )
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'完成：更新 {updated} 条，跳过 {skipped} 条（v1.0 或已有 diff）'
                + (f'，覆盖 {overwritten} 条已有 diff' if overwritten else '')
                + (' [DRY-RUN]' if dry_run else '')
            )
        )
