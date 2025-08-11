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
from rest_framework import serializers, pagination

from Blogs.models import Post, Category


class PostSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(
        read_only=True,
        slug_field='name',
    )
    tags = serializers.SlugRelatedField(
        many=True,
        read_only=True,
        slug_field='name',
    )
    owner = serializers.SlugRelatedField(
        read_only=True,
        slug_field='username',
    )
    created_time = serializers.DateTimeField(
        read_only=True,
        format='%Y-%m-%d %H:%M:%S',
    )
    url = serializers.HyperlinkedIdentityField(view_name='api-post-detail')
    class Meta:
        model = Post
        fields = ['url','title', 'category', 'desc', 'created_time', 'owner', 'tags']


class PostDetailSerializer(PostSerializer):
    class Meta:
        model = Post
        fields = ['id', 'title', 'category', 'tags', 'content', 'created_time', ]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = (
            'id',
            'name',
            'created_time',
        )


class CategoryDetailSerializer(CategorySerializer):
    posts = serializers.SerializerMethodField('paginated_posts')

    def paginated_posts(self, obj):
        posts = obj.post_set.filter(status=Post.STATUS_NORMAL)
        paginator = pagination.PageNumberPagination()
        page = paginator.paginate_queryset(posts, self.context['request'])
        serializer = PostSerializer(page, many=True, context={'request': self.context['request']})
        return {
            'count': posts.count(),
            'results': serializer.data,
            'previous': page.get_previous_link(),
            'next': page.get_next_link(),
        }

    class Meta:
        model = Category
        fields = ('id', 'name', 'created_time','posts')
