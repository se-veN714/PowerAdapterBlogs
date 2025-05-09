from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.generic import DetailView, ListView, TemplateView

from Blogs.models import Post, Tag, Category
from config.models import SideBar


# Create your views here.
class CommonViewMixin:# 不让它继承任何类，而是将这个 Mixin 与有 get_context_data() 方法的视图类一起使用
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'sidebar': SideBar.get_sidebars()
        })


class IndexView(CommonViewMixin, ListView):
    queryset = Post.latest_posts()
    paginate_by = 10
    context_object_name = 'post_list'
    template_name = 'blog/list.html'


class PostListView(ListView):
    queryset = Post.latest_posts()
    paginate_by = 10
    context_object_name = 'post_list'
    template_name = 'blog/list.html'


class PostDetailView(CommonViewMixin, DetailView):
    model = Post
    queryset = Post.objects.filter(status=Post.STATUS_NORMAL)
    template_name = 'blog/detail.html'


class CategoryView(IndexView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category_id = self.kwargs['category_id']
        category = get_object_or_404(Category, id=category_id)
        context.update({
            'category': category,
        })
        return context

    def get_queryset(self):
        queryset = Post.objects.get_queryset()
        category_id = self.kwargs['category_id']
        return queryset.filter(category_id=category_id)


class TagView(IndexView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        tag_id = self.kwargs['tag_id']
        tag = get_object_or_404(Tag, id=tag_id)
        context.update({
            'tag': tag,
        })
        return context

    def get_queryset(self):
        queryset = Post.objects.get_queryset()
        tag_id = self.kwargs['tag_id']
        return queryset.filter(tag_id=tag_id)


def links(request):
    pass
