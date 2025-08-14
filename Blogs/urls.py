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
# Django
from django.urls import path
from django.urls.conf import include
# site
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

# Model
from Blogs.apis import PostViewSet, CategoryViewSet
from Blogs.views import (
    CategoryView, TagView, PostDetailView,
    PostListView, SearchView, PostCreateView)
from Blogs.views import post_img_upload
from comment.views import CommentView

router = DefaultRouter()
router.register('posts', PostViewSet, basename='api_post')
router.register('categories', CategoryViewSet, basename='api_category')

api_urlpatterns = [
    # RESTful API
    path("", include((router.urls, "Blogs"))),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="blogs:Blogs:schema"), name="swagger-ui"),
]

urlpatterns = [
    # CategoryPage
    path("category/<int:category_id>/", CategoryView.as_view(), name="category_list"),
    # TagPage
    path("tag/<int:tag_id>/", TagView.as_view(), name="tag_list"),
    # PostList
    path("post/", PostListView.as_view(), name="post_list"),
    # Post Detail
    path("post/<slug:slug>", PostDetailView.as_view(), name="post_detail"),
    # Search
    path("search/", SearchView.as_view(), name="search"),
    # comment post
    path("post/<int:pk>/comment/", CommentView.as_view(), name="post_comment"),
    # Post_create
    path("post/new/", PostCreateView.as_view(), name="post_create"),
    # img_upload
    path("img_upload/", post_img_upload, name="post_img_upload"),

    # API
    path("api/",include((api_urlpatterns,"Blogs"))),
]


