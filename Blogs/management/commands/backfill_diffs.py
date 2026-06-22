"""
回填 PostRevision.diff_from_previous（迁移前创建的 revision）
用法：python manage.py backfill_diffs [--limit N] [--dry-run]
"""
import logging

from django.core.management.base import BaseCommand
from django.db import models

from Blogs.models import PostRevision
from Blogs.revisions import render_diff

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '回填已有 PostRevision 的 diff_from_previous 字段'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0,
                            help='仅处理最近 N 条 revision（0=全部）')
        parser.add_argument('--dry-run', action='store_true',
                            help='仅检查，不写入')
        parser.add_argument('--force', action='store_true',
                            help='强制重新计算已有 diff（默认跳过已有 diff 的 revision）')

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
            if rev.diff_from_previous and not force:
                skipped += 1
                continue
            if rev.diff_from_previous and force:
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

            diff_html = render_diff(prev.content, rev.content, prev.version, rev.version)
            if dry_run:
                self.stdout.write(f'  [DRY-RUN] {rev} ← {prev}  diff_len={len(diff_html)}')
            else:
                rev.diff_from_previous = diff_html
                rev.save(update_fields=['diff_from_previous'])
                self.stdout.write(f'  [OK] {rev} ← {prev}  diff_len={len(diff_html)}')
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'完成：更新 {updated} 条，跳过 {skipped} 条（v1.0 或已有 diff）'
                + (f'，覆盖 {overwritten} 条已有 diff' if overwritten else '')
                + (' [DRY-RUN]' if dry_run else '')
            )
        )
