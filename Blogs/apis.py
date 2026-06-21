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
import logging

from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

from Blogs.models import Post, Category
from Blogs.serializers import (
    PostSerializer, PostDetailSerializer,
    CategorySerializer, CategoryDetailSerializer
)

logger = logging.getLogger(__name__)


class PostViewSet(viewsets.ModelViewSet):
    serializer_class = PostSerializer
    queryset = Post.objects.filter(status=Post.STATUS_NORMAL)
    permission_classes = [IsAdminUser]

    def retrieve(self, request, *args, **kwargs):
        self.serializer_class = PostDetailSerializer
        return super().retrieve(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        category_id = self.request.query_params.get('category', None)
        if category_id:
            queryset = queryset.filter(category__id=category_id)
        return queryset

    def perform_create(self, serializer):
        instance = serializer.save()
        logger.info(f"API Post 创建: post_id={instance.id} slug={instance.slug} "
                    f"user={self.request.user.id}")

    def perform_update(self, serializer):
        instance = serializer.save()
        logger.info(f"API Post 编辑: post_id={instance.id} slug={instance.slug} "
                    f"user={self.request.user.id}")

    def perform_destroy(self, instance):
        logger.info(f"API Post 删除: post_id={instance.id} slug={instance.slug} "
                    f"user={self.request.user.id}")
        instance.delete()


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    queryset = Category.objects.filter(status=Category.STATUS_NORMAL)

    def retrieve(self, request, *args, **kwargs):
        self.serializer_class = CategoryDetailSerializer
        return super().retrieve(request, *args, **kwargs)
