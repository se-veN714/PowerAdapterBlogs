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
from Blogs.models import Post
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from faker import Faker


class Command(BaseCommand):
    help = "批量生成测试文章"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=50, help="生成文章数量")

    def handle(self, *args, **options):
        count = options["count"]
        user_got = get_user_model()
        user = user_got.objects.first()
        faker = Faker("zh_CN")

        for i in range(count):
            title = faker.sentence(nb_words=5)
            Post.objects.create(
                title=title,
                desc=faker.sentence(nb_words=5),
                content=faker.text(max_nb_chars=500),
                slug=slugify(title) + f"-{i}",
                owner=user,
                category_id=1,
            )

        self.stdout.write(self.style.SUCCESS(f"成功生成 {count} 篇文章"))
