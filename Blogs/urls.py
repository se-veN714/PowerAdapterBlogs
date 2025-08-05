# -*- coding: utf-8 -*-
# @File    : urls.py
# @Time    : 2025/8/4 02:50
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了Blog-urls功能的类和函数。
"""

# here put the import lib
from django.urls import path

from Blogs.views import (
    CategoryView, TagView,PostDetailView,
    PostListView, SearchView, PostCreateView)
from comment.views import CommentView

urlpatterns = [
    # CategoryPage
    path("category/<int:category_id>/", CategoryView.as_view(), name="category_list"),
    # TagPage
    path("tag/<int:tag_id>/", TagView.as_view(), name="tag_list"),
    # PostList
    path("post/", PostListView.as_view(), name="post_list"),
    # Post Detail
    path("post/<int:post_id>.html/", PostDetailView.as_view(), name="post_detail"),
    # Search
    path("search/", SearchView.as_view(), name="search"),
    # comment post
    path("post/<int:pk>/comment/", CommentView.as_view(), name="post_comment"),
    # Post_create
    path('post/new/', PostCreateView.as_view(), name='post_create'),
]
