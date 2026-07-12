# -*- coding: utf-8 -*-
"""
对最近 N 篇文章执行小幅内容修改（删末尾段落），自动迭代 minor 版本。
用途：P2 前端 timeline 组件开发时快速生成多版本测试数据。
用法：python manage.py bump_versions [--count 10] [--dry-run]
"""

import logging
import re

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from Blogs.models import Post
from Blogs.revisions import create_revision

logger = logging.getLogger(__name__)

User = get_user_model()


class Command(BaseCommand):
    help = "对最近文章做小修改（删除末尾段落），生成版本历史数据"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count", type=int, default=10,
            help="处理最近多少篇文章（默认 10）",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="仅预览，不实际修改",
        )

    def _remove_last_paragraph(self, content: str) -> tuple[str, str]:
        """
        删除正文最后一个段落（以空行分隔）。
        返回 (new_content, removed_text)
        """
        # 按空行分割段落
        paragraphs = re.split(r'\n\s*\n', content)
        if len(paragraphs) <= 1:
            # 只有一段，删最后一句
            sentences = re.split(r'(?<=[。！？\.\!\?])\s*', content)
            if len(sentences) <= 1:
                return content[:-10] if len(content) > 10 else content, content[-10:]
            removed = sentences.pop()
            return ''.join(sentences), removed

        removed = paragraphs.pop()
        return '\n\n'.join(paragraphs), removed

    def handle(self, *args, **options):
        count = options["count"]
        dry_run = options["dry_run"]

        # 取最近 N 篇文章
        posts = list(
            Post.objects.filter(status=Post.STATUS_NORMAL)
            .order_by("-created_time")[:count]
        )
        if not posts:
            self.stdout.write(self.style.WARNING("没有找到可用文章"))
            return

        # 获取编辑器（第一个 superuser）
        editor = User.objects.filter(is_superuser=True).first()
        if not editor:
            self.stdout.write(self.style.ERROR("没有找到 superuser，请先创建"))
            return

        self.stdout.write(
            f"编辑器: {editor.username} | 文章数: {len(posts)} | "
            f"{'DRY-RUN 预览模式' if dry_run else '正式执行'}"
        )
        self.stdout.write("-" * 60)

        for i, post in enumerate(posts, 1):
            old_content = post.content
            new_content, removed = self._remove_last_paragraph(old_content)

            if new_content == old_content:
                self.stdout.write(
                    f"[{i}/{len(posts)}] SKIP {post.title[:40]} — 内容太短，无段落可删"
                )
                continue

            removed_preview = removed[:50].replace('\n', '\\n')

            if dry_run:
                self.stdout.write(
                    f"[{i}/{len(posts)}] DRY-RUN {post.title[:40]}\n"
                    f"  旧版本: {post.revisions.count()} 个快照\n"
                    f"  将删除: \"{removed_preview}...\"\n"
                    f"  内容将从 {len(old_content)} → {len(new_content)} 字符"
                )
                continue

            # 更新内容并保存
            post.content = new_content
            post.save(update_fields=["content", "update_time"])

            # 创建修订快照
            revision = create_revision(
                post=post,
                editor=editor,
                change_type="minor",
                edit_summary="精简：删除末尾段落",
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"[{i}/{len(posts)}] {post.title[:40]} → v{revision.version} "
                    f"(删除 {len(old_content)-len(new_content)} 字符)"
                )
            )

        if not dry_run:
            self.stdout.write("-" * 60)
            self.stdout.write(
                self.style.SUCCESS(
                    f"完成！{len(posts)} 篇文章各新增 1 个小版本。"
                )
            )
            self.stdout.write(
                "访问任意文章底部即可看到 timeline 版本历史。"
            )
