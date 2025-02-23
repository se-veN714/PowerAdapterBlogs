from django.http import HttpResponse
from django.shortcuts import render

from Blogs.models import Post, Tag, Category
from config.models import SideBar


# Create your views here.
def post_list(request, category_id=None, tag_id=None):
    posts = None
    tag = None
    category = None

    # 处理 Tag
    if tag_id is not None:
        posts, tag = Post.get_by_tag(tag_id)
    # 处理 Category
    elif category_id is not None:
        posts, category = Post.get_by_category(category_id)

    context = {
        'posts': posts,
        'category': category,
        'tag': tag,
        'sidebars':SideBar.get_sidebars()
    }
    context.update(Category.get_navs())

    return render(request, 'blog/list.html', context=context)


def post_detail(request, post_id=None):
    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        post = None

    context = {'post': post, }
    context.update(Category.get_navs())
    return render(request, 'blog/detail.html', context)


def links(request):
    pass
