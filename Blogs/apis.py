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
from rest_framework.permissions import IsAdminUser

from Blogs.models import Post
from Blogs.serializers import PostSerializer

class PostViewSet(viewsets.ModelViewSet):
    serializer_class = PostSerializer
    queryset = Post.objects.filter(status=Post.STATUS_NORMAL)
    permission_classes = [IsAdminUser]