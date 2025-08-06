# -*- coding: utf-8 -*-
# @File    : serializers.py
# @Time    : 2025/8/6 07:55
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了serializers功能的类和函数。
"""

# here put the import lib
from rest_framework import serializers

from Blogs.models import Post


class PostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ['title', 'category', 'content', 'desc', 'created_time']
