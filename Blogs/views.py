import logging
import os
import uuid
from datetime import date
from urllib.parse import urlencode

from django import VERSION as DJANGO_VERSION
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction, IntegrityError
from django.db.models import Q, F
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls.base import reverse
from django.views.decorators.http import require_POST
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django.views.generic import DetailView, ListView
from django.views.generic.base import TemplateView
from django.views.generic.edit import CreateView, UpdateView

from Blogs.forms import PostForm
from Blogs.image_validation import validate_uploaded_image
from Blogs.models import Post, PostVisit, Tag, Category
from Blogs.revisions import create_revision
from boards.policies import (
    board_for_post,
    can_create_post,
    can_create_post_in_any_board,
    can_edit_post,
    can_view_published_post,
    posts_editable_by,
    posts_visible_to,
    published_posts_visible_to,
)
from config.models import SideBar


# Create your views here.
# 不让它继承任何类，而是将这个 Mixin 与有 get_context_data() 方法的视图类一起使用

class SideBarMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sidebar'] = SideBar.get_sidebars()
        return context


class CategoryNavMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(Category.get_navs())
        return context


class CommonViewMixin(SideBarMixin, CategoryNavMixin):
    pass


logger = logging.getLogger(__name__)

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
        if not can_view_published_post(self.request.user, post):
            logger.warning(f"非授权访问 staff-only 文章: slug={post.slug} "
                           f"user={getattr(self.request.user, 'id', 'anon')}")
            raise Http404("文章不存在")
        return post

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        post = self.object
        revisions = list(post.revisions.all().order_by('-major', '-minor'))

        # 为每个 revision 标注其直接前驱版本
        for i, rev in enumerate(revisions):
            # 下一个（按降序）即是前驱版本（更早的版本）
            if i + 1 < len(revisions):
                rev.prev_version = revisions[i + 1].version
            else:
                rev.prev_version = None

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
        except Exception:
            logger.exception(f"PostVisit PV/UV 更新失败: post_id={post.id} uid={uid}")

        # 记录访问明细
        if increase_pv:
            try:
                PostVisit.objects.get_or_create(
                    uid=uid,
                    post=post,
                    visit_type=1,
                )
            except IntegrityError:
                pass
            except Exception:
                logger.exception(f"PostVisit PV 写入失败: post_id={post.id} uid={uid}")

        try:
            if increase_uv:
                PostVisit.objects.get_or_create(
                    uid=uid,
                    post=post,
                    visit_type=0,
                )
        except IntegrityError:
            pass
        except Exception:
            logger.exception(f"PostVisit UV 写入失败: post_id={post.id} uid={uid}")

class AnonymousPageCacheMixin:
    page_cache_timeout = 15 * 60
    page_cache_key_prefix = None

    def get_page_cache_key_prefix(self):
        return self.page_cache_key_prefix or self.__class__.__name__.lower()

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        vary_dispatch = vary_on_headers("HX-Request")(super().dispatch)
        cached_dispatch = cache_page(
            self.page_cache_timeout,
            key_prefix=self.get_page_cache_key_prefix(),
        )(vary_dispatch)
        return cached_dispatch(request, *args, **kwargs)


class PostListView(AnonymousPageCacheMixin, ListView):
    queryset = Post.get_normal_posts().select_related("owner", "category")
    paginate_by = 10
    context_object_name = 'post_list'
    template_name = 'pages/blog/list.html'
    fragment_template_name = 'pages/blog/_post_browser.html'

    def is_htmx_request(self):
        return self.request.headers.get("HX-Request", "").lower() == "true"

    def get_template_names(self):
        if self.is_htmx_request():
            return [self.fragment_template_name]
        return super().get_template_names()

    def get_queryset(self):
        return published_posts_visible_to(self.request.user, super().get_queryset())

    def get_pagination_query(self):
        """Return non-page query parameters that must survive pagination."""
        return {}

    def get_page_url(self, page_number):
        """Build a canonical page URL with Django 5.2's native query support."""
        query = self.get_pagination_query()
        query["page"] = page_number
        view_name = self.request.resolver_match.view_name
        if DJANGO_VERSION >= (5, 2):
            return reverse(view_name, kwargs=self.kwargs, query=query)

        # Transitional fallback for developers whose old 5.1 environment has
        # not yet been rebuilt. Production is pinned to the supported 5.2 LTS.
        return f"{reverse(view_name, kwargs=self.kwargs)}?{urlencode(query)}"

    def get_stream_pagination(self, page_obj):
        """Expose URL-rich pagination data without assembling URLs in templates."""
        visible_pages = range(
            max(1, page_obj.number - 2),
            min(page_obj.paginator.num_pages, page_obj.number + 2) + 1,
        )
        return {
            "first": self.get_page_url(1),
            "previous": (
                self.get_page_url(page_obj.previous_page_number())
                if page_obj.has_previous()
                else None
            ),
            "pages": [
                {"number": number, "url": self.get_page_url(number)}
                for number in visible_pages
            ],
            "next": (
                self.get_page_url(page_obj.next_page_number())
                if page_obj.has_next()
                else None
            ),
            "last": self.get_page_url(page_obj.paginator.num_pages),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_htmx"] = self.is_htmx_request()
        visible_category_ids = (
            published_posts_visible_to(self.request.user, Post.objects.all())
            .order_by()
            .values("category_id")
        )
        context["categories"] = Category.objects.filter(
            status=Category.STATUS_NORMAL,
            pk__in=visible_category_ids,
        ).order_by("name", "pk")
        page_posts = context["post_list"]
        page_post_ids = [post.pk for post in page_posts]
        editable_ids = set(
            posts_editable_by(
                self.request.user,
                Post.objects.filter(pk__in=page_post_ids),
            )
            .values_list("pk", flat=True)
        )
        for post in page_posts:
            post.can_edit = post.pk in editable_ids
        if context["is_paginated"]:
            context["stream_pagination"] = self.get_stream_pagination(
                context["page_obj"]
            )
        return context


class CategoryView(PostListView):
    template_name = 'pages/blog/cate_list.html'
    category = None

    def get_queryset(self):
        """在统一的可见文章 QuerySet 上按正常分类过滤。"""
        self.category = get_object_or_404(
            Category,
            pk=self.kwargs.get("category_id"),
            status=Category.STATUS_NORMAL,
        )
        return super().get_queryset().filter(category=self.category)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["category"] = self.category
        return context

class TagView(PostListView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
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
            'is_search': True,
            'keyword': self.request.GET.get('keyword', ''),
        })
        return context

    def get_pagination_query(self):
        return {"keyword": self.request.GET.get("keyword", "")}

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
    cache.delete_many(['hot_posts', 'hot_posts:public', 'hot_posts:staff'])


class PostCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = Post
    form_class = PostForm
    template_name = 'pages/blog/post_form.html'

    def test_func(self):
        return can_create_post_in_any_board(self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.owner = self.request.user
        form.instance.status = Post.STATUS_DRAFT
        if not can_create_post(self.request.user, board_for_post(form.instance)):
            raise PermissionDenied
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
        return reverse('Blogs:post_edit', kwargs={'slug': self.object.slug})


class PostEditView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Post
    form_class = PostForm
    template_name = 'pages/blog/post_form.html'

    def get_queryset(self):
        queryset = Post.objects.select_related("category", "owner")
        return posts_visible_to(self.request.user, queryset)

    def test_func(self):
        return can_edit_post(self.request.user, self.get_object())

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        previous = Post.objects.get(pk=self.object.pk)
        form.instance.owner_id = previous.owner_id
        if not can_edit_post(self.request.user, form.instance):
            raise PermissionDenied
        if not self.request.user.is_superuser and previous.status != Post.STATUS_DRAFT:
            form.instance.status = Post.STATUS_DRAFT
        response = super().form_valid(form)
        # 创建修订快照
        change_type = form.cleaned_data.get('change_type', 'minor')
        edit_summary = form.cleaned_data.get('edit_summary', '')
        create_revision(self.object, self.request.user,
                        change_type=change_type, edit_summary=edit_summary)
        changed = []
        if previous.title != self.object.title:
            changed.append("title")
        if previous.content != self.object.content:
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
        if self.object.status == Post.STATUS_NORMAL:
            return reverse('Blogs:post_detail', kwargs={'slug': self.object.slug})
        return reverse('Blogs:post_edit', kwargs={'slug': self.object.slug})


@login_required
@require_POST
def post_img_upload(request):
    if not can_create_post_in_any_board(request.user):
        return JsonResponse({"error": "无权上传文章图片"}, status=403)
    if request.FILES.get("image"):
        image = request.FILES["image"]

        try:
            safe_extension = validate_uploaded_image(image)
        except ValidationError as exc:
            logger.warning(
                "图片上传拒绝: user=%s size=%s content_type=%s reason=%s",
                request.user.id,
                image.size,
                image.content_type,
                exc.messages[0],
            )
            return JsonResponse({'error': exc.messages[0]}, status=400)

        filename = f"{uuid.uuid4().hex}{safe_extension}"
        save_path = os.path.join("post_images", filename)

        # 保存文件
        try:
            path = default_storage.save(save_path, image)
            logger.info(f"图片上传: file={filename} size={image.size} "
                        f"user={getattr(request.user, 'id', 'anon')}")
            return JsonResponse({"url": f"{settings.MEDIA_URL}{path}"})
        except Exception as e:
            logger.exception(f"图片上传失败: file={filename} "
                           f"user={request.user.id} error={e}")
            return JsonResponse({"error": f"图片上传失败: {e}"}, status=500)

    return JsonResponse({"error": "未提供图片文件"}, status=400)


# ============================================================
# 修订历史（v2.0 P2 — htmx HTML 片段端点）
# ============================================================

def revision_body(request, slug, version):
    """GET /post/{slug}/revision/v{major}.{minor}/
    
    htmx 请求 → 返回 HTML 片段（内联查看）
    普通请求 → 返回完整页面（独立页面）
    """
    post = get_object_or_404(Post, slug=slug, status=Post.STATUS_NORMAL)
    if not can_view_published_post(request.user, post):
        raise Http404("文章不存在")
    parts = version.lstrip('v').split('.')
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return HttpResponse('版本号格式无效', status=400)
    major, minor = int(parts[0]), int(parts[1])
    revision = get_object_or_404(
        post.revisions, major=major, minor=minor
    )

    # htmx 请求 → 返回片段
    if request.headers.get('HX-Request'):
        return render(request, 'pages/blog/_revision_body.html', {
            'revision': revision,
            'post': post,
        })

    # 普通请求 → 返回完整页面（用 revision 内容覆盖 post 内容）
    post.title = f"{revision.title} — v{revision.version}"
    post.content = revision.content
    revisions = list(post.revisions.all().order_by('-major', '-minor'))
    for i, rev in enumerate(revisions):
        rev.prev_version = revisions[i + 1].version if i + 1 < len(revisions) else None
    return render(request, 'pages/blog/detail.html', {
        'post': post,
        'revisions': revisions,
        'revision_count': len(revisions),
        'show_timeline': len(revisions) > 1,
        'object': post,
    })


def revision_diff(request, slug):
    """GET /post/{slug}/diff/?from=1.0&to=2.0 — 仅允许相邻版本对比

    严格校验：from 必须是 to 的直接前驱，否则返回 400。
    优先使用预计算的 diff_from_previous。
    """
    from .revisions import render_diff as compute_diff

    post = get_object_or_404(Post, slug=slug, status=Post.STATUS_NORMAL)
    if not can_view_published_post(request.user, post):
        raise Http404("文章不存在")
    from_ver = request.GET.get('from', '')
    to_ver = request.GET.get('to', '')

    if not from_ver or not to_ver:
        return HttpResponse('请选择两个版本进行对比', status=400)

    if from_ver == to_ver:
        return HttpResponse('不能对比相同版本', status=400)

    try:
        rev_from = _get_revision_by_version(post, from_ver)
        rev_to = _get_revision_by_version(post, to_ver)
    except ValueError as e:
        return HttpResponse(str(e), status=400)

    if not rev_from or not rev_to:
        return HttpResponse('版本号不存在', status=404)

    # 严格检查：必须是相邻版本（to 的直接前驱是 from）
    prev = _get_adjacent_previous(post, rev_to)
    if not prev or prev.version != from_ver:
        return HttpResponse(
            f'仅支持相邻版本对比。v{to_ver} 的直接前驱是 v{prev.version if prev else "?"}',
            status=400,
        )

    # 优先预计算 diff
    diff_html = rev_to.diff_from_previous or compute_diff(
        rev_from.content, rev_to.content, from_ver, to_ver,
    )

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


def _get_adjacent_previous(post, revision):
    """获取指定 revision 的直接前驱（按 major.minor 排序）"""
    return post.revisions.filter(
        Q(major__lt=revision.major) |
        Q(major=revision.major, minor__lt=revision.minor)
    ).order_by('-major', '-minor').first()
