# -*- coding: utf-8 -*-
# @File    : generate_posts.py
# @Time    : 2025/8/18 18:03
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了生成post测试用例功能的类和函数。
"""
import logging
import uuid

from Blogs.models import Category, Post
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Q
from faker import Faker

from boards.models import Board

logger = logging.getLogger(__name__)

GENERATED_SLUG_PREFIX = "generated-post-"


class Command(BaseCommand):
    help = "批量生成测试文章"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=50, help="生成文章数量")
        parser.add_argument(
            "--clear",
            action="store_true",
            help="生成前仅清理由本命令创建、slug 带 generated-post- 前缀的文章",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("generate_posts 仅允许在 DEBUG=True 的开发或测试环境运行")

        count = options["count"]
        clear = options["clear"]
        if count < 0:
            raise CommandError("--count 不能小于 0")

        user = (
            get_user_model()
            .objects.filter(is_active=True, is_superuser=True)
            .order_by("pk")
            .first()
        )
        if user is None:
            raise CommandError("没有可用的激活 superuser，无法安全生成测试文章")

        eligible_category_ids = (
            Board.objects.exclude(category_id=None)
            .values("category_id")
            .annotate(
                board_count=Count("pk"),
                active_board_count=Count("pk", filter=Q(is_active=True)),
            )
            .filter(board_count=1, active_board_count=1)
            .values("category_id")
        )
        categories = list(
            Category.objects.filter(
                status=Category.STATUS_NORMAL,
                pk__in=eligible_category_ids,
            ).order_by("name", "pk")
        )
        if not categories:
            raise CommandError("没有关联唯一活跃 Board 的正常分类，请先检查 Board 配置")

        faker = Faker("zh_CN")
        category_names = [category.name for category in categories]
        logger.info(
            "generate_posts 开始: count=%s user_id=%s categories=%s clear=%s",
            count,
            user.pk,
            category_names,
            clear,
        )

        with transaction.atomic():
            deleted_posts = 0
            if clear:
                generated_posts = Post.objects.filter(
                    slug__startswith=GENERATED_SLUG_PREFIX,
                )
                deleted_posts = generated_posts.count()
                generated_posts.delete()

            for index in range(count):
                title = faker.sentence(nb_words=5)
                category = categories[index % len(categories)]
                Post.objects.create(
                    title=title,
                    desc=faker.sentence(nb_words=5),
                    content=faker.text(max_nb_chars=500),
                    slug=f"{GENERATED_SLUG_PREFIX}{uuid.uuid4().hex}",
                    owner=user,
                    category=category,
                )

        if clear:
            logger.info("generate_posts 清理完成: deleted_posts=%s", deleted_posts)
            self.stdout.write(
                self.style.WARNING(f"已清理 {deleted_posts} 篇命令生成的测试文章")
            )

        logger.info("generate_posts 完成: created=%s", count)
        self.stdout.write(self.style.SUCCESS(f"成功生成 {count} 篇文章"))
