"""
URL configuration for PowerAdapterBlogs project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path

from comment.views import CommentView
from .cus_site import custom_site
from config.views import LinkListView
from Blogs.views import (
    IndexView, CategoryView, TagView,
    PostDetailView, PostListView, SearchView
)

urlpatterns = [
    path("super_admin/", admin.site.urls, name="super_admin"),
    path("admin/", custom_site.urls, name="admin"),
    # Homepage

    # PostPage
    path("", IndexView.as_view(), name="index"),
    # CategoryPage
    path("category/<int:category_id>/", CategoryView.as_view(), name="category_list"),
    # TagPage
    path("tag/<int:tag_id>/", TagView.as_view(), name="tag_list"),
    # PostList
    path("post/", PostListView.as_view(), name="post_list"),
    # Post Detail
    path("post/<int:post_id>.html/", PostDetailView.as_view(), name="post_detail"),
    # LinksPage
    path("links/", LinkListView.as_view(), name="links"),
    # Search
    path('search/', SearchView.as_view(), name="search"),
    #comment post
    path('comment/', CommentView.as_view(), name="comment"),
]
