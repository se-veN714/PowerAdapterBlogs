import logging
import os
import uuid
from datetime import date

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction, IntegrityError
from django.db.models import Q, F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls.base import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import cache_page
from django.views.generic import DetailView, ListView
from django.views.generic.base import TemplateView
from django.views.generic.edit import CreateView, UpdateView

from Blogs.forms import PostForm
from Blogs.models import Post, PostVisit, Tag, Category
from config.models import SideBar


# Create your views here.
# 不让它继承任何类，而是将这个 Mixin 与有 get_context_data() 方法的视图类一起使用

class SideBarMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sidebar'] = SideBar.get_sidebars()
        print("This is sidebar context:(T_T)", context['sidebar'])
        return context


class CategoryNavMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(Category.get_navs())
        print("This is nav context:(T_T)", context['cate_navs'])
        return context


class CommonViewMixin(SideBarMixin, CategoryNavMixin):
    pass


class LoggingMixin:
    def log_action(self, request, action, **kwargs):
        username = getattr(request.user, 'username', str(request.user))
        logger = logging.getLogger(__name__)
        logger.info(f"用户-[{username}]:{action}", extra=kwargs)


class IndexView(CommonViewMixin, TemplateView):
    template_name = '../bulma/base/index.html'


class PostDetailView(CommonViewMixin, DetailView):
    queryset = Post.get_normal_posts()
    template_name = 'blog/detail.html'
    context_object_name = 'post'

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        self.handle_visit()
        return response

    def get_object(self, queryset=None):
        return get_object_or_404(Post, slug=self.kwargs['slug'], status=Post.STATUS_NORMAL)

    def handle_visit(self):

        uid = self.request.uid
        post = self.object
        visit_date = date.today()

        pv_key = f'pv:{uid}:{post.id}'
        uv_key = f'uv:{uid}:{visit_date}:{post.id}'

        increase_pv = False
        increase_uv = False

        if not cache.get(pv_key):
            increase_pv = True
            cache.set(pv_key, 1, 1 * 60)  # 1min 有效

        if not PostVisit.objects.filter(uid=uid, post=post).exists():
            increase_uv = True
            cache.set(uv_key, 1, 24 * 60 * 60)  # 24h 有效

        # 使用事务
        with transaction.atomic():
            if increase_pv or increase_uv:
                update_kwargs = {}
                if increase_pv:
                    update_kwargs['pv'] = F('pv') + 1
                if increase_uv:
                    update_kwargs['uv'] = F('uv') + 1

                Post.objects.filter(pk=post.id).update(**update_kwargs)

        # 记录访问明细
        if increase_pv:
            try:
                PostVisit.objects.get_or_create(
                    uid=uid,
                    post=post,
                    visit_type=1,
                    created_time=visit_date,
                )
            except IntegrityError:
                pass

        try:
            if increase_uv:
                PostVisit.objects.get_or_create(
                    uid=uid,
                    post=post,
                    visit_type=0,
                    created_time=visit_date,
                )
        except IntegrityError:
            pass

class AnonymousPageCacheMixin:
    page_cache_timeout = 15 * 60
    page_cache_key_prefix = None

    def get_page_cache_key_prefix(self):
        return self.page_cache_key_prefix or self.__class__.__name__.lower()

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        cached_dispatch = cache_page(
            self.page_cache_timeout,
            key_prefix=self.get_page_cache_key_prefix(),
        )(super().dispatch)
        return cached_dispatch(request, *args, **kwargs)


class PostListView(AnonymousPageCacheMixin, ListView):
    queryset = Post.get_normal_posts().select_related("owner", "category")
    paginate_by = 10
    context_object_name = 'post_list'
    template_name = 'blog/list.html'


class CategoryView(CommonViewMixin, ListView):
    paginate_by = 10
    template_name = 'blog/cate_list.html'
    context_object_name = 'cate_posts'
    cate_list = None

    def get_queryset(self):
        """ 重写 queryset，根据分类过滤 """
        self.cate_list = get_object_or_404(Category, pk=self.kwargs.get("category_id"))
        return Post.get_by_category(self.cate_list.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cate"] = self.cate_list
        print("This is cate_list context:(T_T)", context['cate_posts'])
        return context

class TagView(PostListView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        tag_id = self.kwargs.get('tag_id')
        tag = get_object_or_404(Tag, id=tag_id)
        context.update({
            'tag': tag,
        })
        return context

    def get_queryset(self):
        """ 重写 queryset，根据标签过滤（ManyToMany 跨表）"""
        queryset = super().get_queryset()
        tag_id = self.kwargs.get('tag_id')
        return queryset.filter(tag__id=tag_id)


class SearchView(PostListView):
    template_name = 'blog/search_result.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'keyword': self.request.GET.get('keyword', ''),
        })
        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        keyword = self.request.GET.get('keyword', '').strip()
        if not keyword:
            return queryset
        return queryset.filter(Q(title__icontains=keyword) | Q(content__icontains=keyword))


def clear_page_caches():
    """清除所有页面级缓存， 在文章创建/编辑后调用， 确保前台立即看到更新。"""
    try:
        # 1. 清理整页缓存 (AnonymousPageCacheMixin 产生的 cache_page 缓存)
        cache.delete_pattern("*views.decorators.cache.cache_page.*")
        # 2. 清理模板片段缓存 (base.html {% cache 900 cache_sidebar/cache_cate %}
        #    以及 cate_list.html {% cache 900 cache_cate_post ... %})
        cache.delete_pattern("*template.cache.*")
    except AttributeError:
        # 非 Redis 后端 (如 LocMemCache) 不支持 delete_pattern 通配符
        pass
    # 3. 清理 hot_posts 查询缓存
    cache.delete('hot_posts')


class PostCreateView(LoginRequiredMixin, LoggingMixin, CreateView):
    model = Post
    form_class = PostForm
    template_name = 'blog/post_form.html'

    def form_valid(self, form):
        form.instance.owner = self.request.user
        response = super().form_valid(form)
        self.log_action(self.request, f"post-{form.instance.title}")
        clear_page_caches()
        return response

    def get_success_url(self):
        return reverse('Blogs:post_detail', kwargs={'slug': self.object.slug})


class PostEditView(LoginRequiredMixin, UpdateView):
    model = Post
    form_class = PostForm
    template_name = 'blog/post_form.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        clear_page_caches()
        return response

    def get_success_url(self):
        return reverse('Blogs:post_detail', kwargs={'slug': self.object.slug})


@csrf_exempt
def post_img_upload(request):
    if request.method == "POST" and request.FILES.get("image"):
        image = request.FILES["image"]

        # 生成安全文件名
        ext = image.name.split('.')[-1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        save_path = os.path.join("post_images", filename)

        # 保存文件
        path = default_storage.save(save_path, image)

        return JsonResponse({"url": f"{settings.MEDIA_URL}{path}"})

    return JsonResponse({"error": "No image uploaded"}, status=400)
