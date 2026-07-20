# -*- coding: utf-8 -*-
# @File    : apis.py
# @Time    : 2025/8/6 07:58
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了apis功能的类和函数。
"""
# here put the import lib
from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from Blogs.models import Post, Category
from Blogs.serializers import (
    PostSerializer, PostDetailSerializer,
    CategorySerializer, CategoryDetailSerializer
)
from boards.policies import published_posts_visible_to


class PostViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PostSerializer
    queryset = Post.objects.select_related("category", "owner").prefetch_related("tag")
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PostDetailSerializer
        return PostSerializer

    def get_queryset(self):
        return published_posts_visible_to(self.request.user, super().get_queryset())

    def filter_queryset(self, queryset):
        category_id = self.request.query_params.get('category', None)
        if category_id:
            queryset = queryset.filter(category__id=category_id)
        return super().filter_queryset(queryset)


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CategorySerializer
    queryset = Category.objects.filter(status=Category.STATUS_NORMAL)
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return CategoryDetailSerializer
        return CategorySerializer

    def get_queryset(self):
        visible_category_ids = published_posts_visible_to(
            self.request.user,
            Post.objects.all(),
        ).values("category_id")
        return super().get_queryset().filter(pk__in=visible_category_ids).distinct()
