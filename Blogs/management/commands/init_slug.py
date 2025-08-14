# -*- coding: utf-8 -*-
# @File    : init_slug.py
# @Time    : 2025/8/13 03:10
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了slug初始化功能的类和函数。
"""

# here put the import lib
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from Blogs.models import Post


class Command(BaseCommand):
    help = "Initialize slug field for Posts that have empty slug"

    def handle(self, *args, **options):
        posts = Post.objects.filter(slug__isnull=True) | Post.objects.filter(slug="")
        if not posts.exists():
            self.stdout.write(self.style.SUCCESS("✅ No posts without slug. Nothing to do."))
            return

        for post in posts:
            base_slug = slugify(post.title)
            slug = base_slug
            counter = 0

            # 确保唯一性
            while Post.objects.filter(slug=slug).exclude(pk=post.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            post.slug = slug
            post.save()
            self.stdout.write(self.style.SUCCESS(f"✔ Generated slug '{slug}' for post '{post.title}'"))

        self.stdout.write(self.style.SUCCESS("🎉 All missing slugs have been initialized."))
