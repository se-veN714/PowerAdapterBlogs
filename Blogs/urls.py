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

# Model
from Blogs.views import (
    CategoryView, TagView, PostDetailView,
    PostArchiveView, PostListView, PostReviewWorkspaceView, SearchView,
    PostCreateView, PostEditView,
    revision_body, revision_diff,
    submit_own_post_for_review,
)
from Blogs.views import post_img_upload
from comment.views import CommentDeleteView, CommentView

urlpatterns = [
    # CategoryPage
    path("category/<int:category_id>/", CategoryView.as_view(), name="category_list"),
    # TagPage
    path("tag/<int:tag_id>/", TagView.as_view(), name="tag_list"),
    # PostList
    path("post/", PostListView.as_view(), name="post_list"),
    path("archive/", PostArchiveView.as_view(), name="post_archive"),
    path("review/", PostReviewWorkspaceView.as_view(), name="review_workspace"),
    # Post Detail
    path("post/<slug:slug>", PostDetailView.as_view(), name="post_detail"),
    # Search
    path("search/", SearchView.as_view(), name="search"),
    # comment post
    path("post/<slug:slug>/comment/", CommentView.as_view(), name="post_comment"),
    path("comment/<int:pk>/delete/", CommentDeleteView.as_view(), name="comment_delete"),
    # post_create
    path("post/new/", PostCreateView.as_view(), name="post_create"),
    # post_edit
    path("post/<slug:slug>/edit/",PostEditView.as_view(), name="post_edit"),
    path(
        "post/<slug:slug>/submit/",
        submit_own_post_for_review,
        name="post_submit_review",
    ),
    # img_upload
    path("img_upload/", post_img_upload, name="post_img_upload"),

    # 修订历史（v2.0 P2 — htmx HTML 片段端点）
    path("post/<slug:slug>/revision/<str:version>/", revision_body, name="revision_body"),
    path("post/<slug:slug>/diff/", revision_diff, name="revision_diff"),

]


