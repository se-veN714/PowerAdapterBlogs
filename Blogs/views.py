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
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls.base import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import cache_page
from django.views.generic import DetailView, ListView
from django.views.generic.base import TemplateView
from django.views.generic.edit import CreateView, UpdateView

from Blogs.forms import PostForm
from Blogs.models import Post, PostVisit, Tag, Category
from Blogs.revisions import create_revision, can_view_staff_only
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


logger = logging.getLogger(__name__)

class LoggingMixin:
    """已弃用：保留以兼容旧代码，新日志直接在视图方法中调用 logger。"""
    def log_action(self, request, action, **kwargs):
        username = getattr(request.user, 'username', str(request.user))
        logger.info(f"用户-[{username}]:{action}", extra=kwargs)


class IndexView(CommonViewMixin, TemplateView):
    template_name = 'pages/index.html'


class PostDetailView(CommonViewMixin, DetailView):
    queryset = Post.get_normal_posts()
    template_name = 'pages/blog/detail.html'
    context_object_name = 'post'

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        self.handle_visit()
        return response

    def get_object(self, queryset=None):
        post = get_object_or_404(Post, slug=self.kwargs['slug'], status=Post.STATUS_NORMAL)
        # visibility 检查：staff-only 文章非内部用户 → 404
        if post.visibility == Post.VISIBILITY_STAFF_ONLY and not can_view_staff_only(self.request.user):
            logger.warning(f"非授权访问 staff-only 文章: slug={post.slug} "
                           f"user={getattr(self.request.user, 'id', 'anon')}")
            raise Http404("文章不存在")
        return post

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        post = self.object
        revisions = post.revisions.all().order_by('-major', '-minor')
        context['revisions'] = revisions
        context['revision_count'] = len(revisions)
        context['show_timeline'] = len(revisions) > 1
        return context

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
        try:
            with transaction.atomic():
                if increase_pv or increase_uv:
                    update_kwargs = {}
                    if increase_pv:
                        update_kwargs['pv'] = F('pv') + 1
                    if increase_uv:
                        update_kwargs['uv'] = F('uv') + 1

                    Post.objects.filter(pk=post.id).update(**update_kwargs)
        except Exception as e:
            logger.exception(f"PostVisit PV/UV 更新失败: post_id={post.id} uid={uid}")

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
            except Exception as e:
                logger.exception(f"PostVisit PV 写入失败: post_id={post.id} uid={uid}")

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
        except Exception as e:
            logger.exception(f"PostVisit UV 写入失败: post_id={post.id} uid={uid}")

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
    template_name = 'pages/blog/list.html'

    def get_queryset(self):
        qs = super().get_queryset()
        if not can_view_staff_only(self.request.user):
            qs = qs.exclude(visibility=Post.VISIBILITY_STAFF_ONLY)
        return qs


class CategoryView(CommonViewMixin, ListView):
    paginate_by = 10
    template_name = 'pages/blog/cate_list.html'
    context_object_name = 'cate_posts'
    cate_list = None

    def get_queryset(self):
        """ 重写 queryset，根据分类过滤 """
        self.cate_list = get_object_or_404(Category, pk=self.kwargs.get("category_id"))
        qs = Post.get_by_category(self.cate_list.id)
        if not can_view_staff_only(self.request.user):
            qs = qs.exclude(visibility=Post.VISIBILITY_STAFF_ONLY)
        return qs

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
    template_name = 'pages/blog/search_result.html'

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
    except Exception as e:
        logger.warning(f"缓存清除失败: error={e}")
    # 3. 清理 hot_posts 查询缓存
    cache.delete('hot_posts')


class PostCreateView(LoginRequiredMixin, LoggingMixin, CreateView):
    model = Post
    form_class = PostForm
    template_name = 'pages/blog/post_form.html'

    def form_valid(self, form):
        form.instance.owner = self.request.user
        response = super().form_valid(form)
        # 创建 v1.0 初始快照
        create_revision(self.object, self.request.user,
                        change_type='major', edit_summary='初始发布')
        logger.info(f"Post 创建: post_id={self.object.id} slug={self.object.slug} "
                    f"user={self.request.user.id} category_id={self.object.category_id}")
        clear_page_caches()
        return response

    def form_invalid(self, form):
        logger.warning(f"Post 创建表单失败: user={self.request.user.id} "
                       f"errors={form.errors}")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse('Blogs:post_detail', kwargs={'slug': self.object.slug})


class PostEditView(LoginRequiredMixin, UpdateView):
    model = Post
    form_class = PostForm
    template_name = 'pages/blog/post_form.html'

    def form_valid(self, form):
        old_title = self.object.title
        old_content = self.object.content
        response = super().form_valid(form)
        # 创建修订快照
        change_type = form.cleaned_data.get('change_type', 'minor')
        edit_summary = form.cleaned_data.get('edit_summary', '')
        create_revision(self.object, self.request.user,
                        change_type=change_type, edit_summary=edit_summary)
        changed = []
        if old_title != self.object.title:
            changed.append("title")
        if old_content != self.object.content:
            changed.append("content")
        logger.info(f"Post 编辑: post_id={self.object.id} slug={self.object.slug} "
                    f"user={self.request.user.id} changed={changed}")
        clear_page_caches()
        return response

    def form_invalid(self, form):
        logger.warning(f"Post 编辑表单失败: post_id={self.object.id} "
                       f"user={self.request.user.id} errors={form.errors}")
        return super().form_invalid(form)

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
        try:
            path = default_storage.save(save_path, image)
            logger.info(f"图片上传: file={filename} size={image.size} "
                        f"user={getattr(request.user, 'id', 'anon')}")
            return JsonResponse({"url": f"{settings.MEDIA_URL}{path}"})
        except Exception as e:
            logger.exception(f"图片上传失败: file={filename} "
                           f"user={getattr(request.user, 'id', 'anon')} error={e}")
            return JsonResponse({"error": f"图片上传失败: {e}"}, status=500)

    return JsonResponse({"error": "No image uploaded"}, status=400)


# ============================================================
# 修订历史（v2.0 P2 — htmx HTML 片段端点）
# ============================================================

def revision_body(request, slug, version):
    """GET /post/{slug}/revision/v{major}.{minor}/ — 返回版本内容的 HTML 片段（htmx）"""
    post = get_object_or_404(Post, slug=slug, status=Post.STATUS_NORMAL)
    parts = version.lstrip('v').split('.')
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return HttpResponse('版本号格式无效', status=400)
    major, minor = int(parts[0]), int(parts[1])
    revision = get_object_or_404(
        post.revisions, major=major, minor=minor
    )
    return render(request, 'pages/blog/_revision_body.html', {
        'revision': revision,
        'post': post,
    })


def revision_diff(request, slug):
    """GET /post/{slug}/diff/?from=1.0&to=2.0 — 返回 diff HTML 片段（htmx）
    
    优先使用预计算的 diff_from_previous（零计算开销）。
    非相邻版本或旧数据无预计算时，实时生成。
    """
    from .revisions import render_diff as compute_diff

    post = get_object_or_404(Post, slug=slug, status=Post.STATUS_NORMAL)
    from_ver = request.GET.get('from', '')
    to_ver = request.GET.get('to', '')

    if not from_ver or not to_ver:
        return HttpResponse('请选择两个版本进行对比', status=400)

    try:
        rev_from = _get_revision_by_version(post, from_ver)
        rev_to = _get_revision_by_version(post, to_ver)
    except ValueError as e:
        return HttpResponse(str(e), status=400)

    if not rev_from or not rev_to:
        return HttpResponse('版本号不存在', status=404)

    # 优先使用预计算 diff（写时计算，读时零成本）
    diff_html = None
    if from_ver == '1.0' and rev_to and rev_to.major == 1 and rev_to.minor == 0:
        pass  # v1.0 没有前驱
    elif rev_to and rev_to.diff_from_previous:
        # 检查是否正好是相邻版本，且 diff 对应
        prev = post.revisions.filter(
            major__lt=rev_to.major
        ).order_by('-major', '-minor').first() or \
               post.revisions.filter(
                   major=rev_to.major, minor__lt=rev_to.minor
               ).order_by('-major', '-minor').first()
        if prev and prev.version == from_ver:
            diff_html = rev_to.diff_from_previous

    if not diff_html:
        diff_html = compute_diff(rev_from.content, rev_to.content, from_ver, to_ver)

    return render(request, 'pages/blog/_revision_diff.html', {
        'diff_html': diff_html,
        'from_version': from_ver,
        'to_version': to_ver,
        'from_title': rev_from.title,
        'to_title': rev_to.title,
    })


def _get_revision_by_version(post, ver_str: str):
    """版本号字符串 → PostRevision 实例的辅助函数"""
    parts = ver_str.strip().lstrip('v').split('.')
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"版本号格式无效: {ver_str}")
    return post.revisions.filter(major=int(parts[0]), minor=int(parts[1])).first()
