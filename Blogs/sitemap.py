# -*- coding: utf-8 -*-
# @File    : sitemap.py
# @Time    : 2025/7/8 02:42
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了sitemap功能的类和函数。
"""

# here put the import lib
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Post

class PostSitemap(Sitemap):
    changefreq = "always"
    priority = 1.0
    protocol = "https"

    def items(self):
        return Post.objects.filter(status=Post.STATUS_NORMAL)

    def lastmod(self, item):
        return item.created_time

    def location(self, item):
        return reverse('post_detail', args=[item.pk])