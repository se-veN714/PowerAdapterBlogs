import logging
import os
import uuid
from datetime import date
from itertools import groupby
from urllib.parse import urlencode

from django import VERSION as DJANGO_VERSION
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction, IntegrityError
from django.db.models import Q, F
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.templatetags.static import static
from django.urls.base import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.decorators.cache import cache_page, never_cache
from django.views.decorators.vary import vary_on_headers
from django.views.generic import DetailView, ListView
from django.views.generic.base import TemplateView
from django.views.generic.edit import CreateView, UpdateView

from Blogs.forms import PostForm
from Blogs.image_validation import validate_uploaded_image
from Blogs.models import Post, PostVisit, Tag, Category
from Blogs.services import (
    RevisionConflict,
    approve_post,
    commit_post_form,
    reject_post,
    submit_post_for_review,
    unpublish_post,
)
from boards.policies import (
    board_for_post,
    can_access_post_admin,
    can_create_post,
    can_create_post_in_any_board,
    can_edit_post,
    can_publish_post,
    can_review_post,
    can_submit_post,
    can_view_post_detail,
    posts_editable_by,
    posts_publishable_by,
    posts_visible_to,
    published_posts_visible_to,
)
from config.models import SideBar
from boards.models import Board
from PowerAdapterBlogs.public_urls import public_absolute_url


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

WORKFLOW_ACTIONS = {
    "submit": (submit_post_for_review, "草稿已提交审核。"),
    "approve": (approve_post, "文章已审核通过并发布。"),
    "reject": (reject_post, "文章已驳回并退回草稿。"),
    "unpublish": (unpublish_post, "文章已下架。"),
}

class IndexView(CommonViewMixin, TemplateView):
    template_name = 'pages/index.html'


@method_decorator(never_cache, name="dispatch")
class PostReviewWorkspaceView(LoginRequiredMixin, TemplateView):
    """A focused, Board-scoped UI for valid post workflow transitions."""

    template_name = "pages/blog/review_workspace.html"
    published_fragment_template_name = "pages/blog/_review_published_results.html"
    published_page_size = 8
    published_cursor_salt = "blogs.review-workspace.published"
    published_filter_names = ("board", "tag", "author", "q")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not can_access_post_admin(request.user):
            raise PermissionDenied("当前账号没有稿件流程权限。")
        return super().dispatch(request, *args, **kwargs)

    def _scoped_posts(self):
        queryset = Post.objects.select_related("category", "owner")
        return posts_visible_to(self.request.user, queryset)

    def _published_filters(self, source=None):
        source = source or self.request.GET
        limits = {"board": 64, "tag": 20, "author": 20, "q": 100}
        return {
            name: str(source.get(name, "")).strip()[: limits[name]]
            for name in self.published_filter_names
            if str(source.get(name, "")).strip()
        }

    def _published_base_queryset(self):
        queryset = Post.objects.filter(status=Post.STATUS_NORMAL).select_related(
            "category",
            "owner",
        )
        return posts_publishable_by(self.request.user, queryset)

    @staticmethod
    def _positive_int(value):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def _filter_published_queryset(self, queryset, filters):
        if board_slug := filters.get("board"):
            category_ids = Board.objects.filter(
                slug=board_slug,
                is_active=True,
                category_id__isnull=False,
            ).values("category_id")
            queryset = queryset.filter(category_id__in=category_ids)
        if tag_value := filters.get("tag"):
            tag_id = self._positive_int(tag_value)
            queryset = queryset.filter(tag__pk=tag_id) if tag_id else queryset.none()
        if author_value := filters.get("author"):
            author_id = self._positive_int(author_value)
            queryset = (
                queryset.filter(owner_id=author_id) if author_id else queryset.none()
            )
        if query := filters.get("q"):
            queryset = queryset.filter(
                Q(title__icontains=query) | Q(desc__icontains=query)
            )
        return queryset.distinct()

    def _decode_published_cursor(self, token, filters):
        if not token:
            return None
        try:
            payload = signing.loads(
                token,
                salt=self.published_cursor_salt,
                max_age=60 * 60,
            )
            created_time = parse_datetime(payload["created_time"])
            pk = int(payload["pk"])
        except (signing.BadSignature, KeyError, TypeError, ValueError):
            return None
        if payload.get("filters") != filters or created_time is None or pk <= 0:
            return None
        return created_time, pk

    def _encode_published_cursor(self, post, filters):
        return signing.dumps(
            {
                "created_time": post.created_time.isoformat(),
                "pk": post.pk,
                "filters": filters,
            },
            salt=self.published_cursor_salt,
            compress=True,
        )

    def _published_url(self, filters, *, cursor=None):
        query = {**filters, "section": "published"}
        if cursor:
            query["published_cursor"] = cursor
        return f'{reverse("blogs:review_workspace")}?{urlencode(query)}'

    def _published_context(self, *, include_filters=False):
        filters = self._published_filters()
        base_queryset = self._published_base_queryset()
        queryset = self._filter_published_queryset(base_queryset, filters)
        cursor = self._decode_published_cursor(
            self.request.GET.get("published_cursor", ""),
            filters,
        )
        if cursor:
            created_time, pk = cursor
            queryset = queryset.filter(
                Q(created_time__lt=created_time)
                | Q(created_time=created_time, pk__lt=pk)
            )

        rows = list(
            queryset.order_by("-created_time", "-pk").prefetch_related("tag")[
                : self.published_page_size + 1
            ]
        )
        published_posts = rows[: self.published_page_size]
        next_cursor = None
        if len(rows) > self.published_page_size:
            next_cursor = self._encode_published_cursor(published_posts[-1], filters)

        context = {
            "published_posts": published_posts,
            "published_filters": filters,
            "published_next_url": (
                self._published_url(filters, cursor=next_cursor)
                if next_cursor
                else None
            ),
            "published_is_append": bool(cursor),
        }
        if include_filters:
            visible_category_ids = base_queryset.order_by().values("category_id")
            context["published_filter_boards"] = Board.objects.filter(
                is_active=True,
                category_id__in=visible_category_ids,
            ).order_by("sort_order", "pk")
            context["published_filter_tags"] = Tag.objects.filter(
                posts__in=base_queryset
            ).distinct().order_by("name", "pk")
            context["published_filter_authors"] = get_user_model().objects.filter(
                pk__in=base_queryset.order_by().values("owner_id")
            ).order_by("username", "pk")
        return context

    def get(self, request, *args, **kwargs):
        is_fragment = (
            request.headers.get("HX-Request", "").lower() == "true"
            and request.GET.get("section") == "published"
        )
        if is_fragment:
            return render(
                request,
                self.published_fragment_template_name,
                self._published_context(),
            )
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scoped_posts = self._scoped_posts()
        context["draft_posts"] = [
            post
            for post in scoped_posts.filter(status=Post.STATUS_DRAFT)
            if can_submit_post(self.request.user, post)
        ]
        context["review_posts"] = [
            post
            for post in scoped_posts.filter(status=Post.STATUS_REVIEW)
            if can_review_post(self.request.user, post)
            and can_publish_post(self.request.user, post)
        ]
        context.update(self._published_context(include_filters=True))
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("workflow_action", "")
        workflow = WORKFLOW_ACTIONS.get(action)
        if workflow is None:
            messages.error(request, "未知的稿件操作。")
            return HttpResponseRedirect(reverse("blogs:review_workspace"))

        post = get_object_or_404(self._scoped_posts(), pk=request.POST.get("post_id"))
        service, success_message = workflow
        try:
            service(post=post, user=request.user)
        except PermissionDenied:
            messages.error(request, "当前账号没有执行此操作的权限。")
        except ValidationError as exc:
            messages.warning(request, exc.messages[0])
        else:
            messages.success(request, success_message)
        filters = self._published_filters(request.POST)
        target = reverse("blogs:review_workspace")
        if filters:
            target = f"{target}?{urlencode(filters)}"
        return HttpResponseRedirect(target)


@login_required
@require_POST
def submit_own_post_for_review(request, slug):
    """Submit one owned draft and return to the author's management surface."""
    post = get_object_or_404(
        Post.objects.select_related("category", "owner"),
        slug=slug,
        owner=request.user,
    )
    try:
        submit_post_for_review(post=post, user=request.user)
    except PermissionDenied:
        messages.error(request, "当前账号没有提交这篇草稿的权限。")
    except ValidationError as exc:
        messages.warning(request, exc.messages[0])
    else:
        messages.success(request, "草稿已提交审核。")
    return HttpResponseRedirect(reverse("accounts:my-profile"))


class PostDetailView(CommonViewMixin, DetailView):
    model = Post
    template_name = 'pages/blog/detail.html'
    context_object_name = 'post'

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        self.handle_visit()
        return response

    def get_object(self, queryset=None):
        post = get_object_or_404(
            Post.objects.select_related("category", "owner", "owner__profile"),
            slug=self.kwargs['slug'],
        )
        if not can_view_post_detail(self.request.user, post):
            logger.warning(f"非授权访问文章详情: slug={post.slug} "
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
        context['can_edit_current_post'] = can_edit_post(
            self.request.user,
            post,
        )
        context["seo_description"] = post.desc or post.title
        context["seo_canonical_url"] = public_absolute_url(post.get_absolute_url())
        context["seo_image_url"] = public_absolute_url(
            post.cover.url if post.cover else static(post.default_cover_static_path)
        )
        if post.status == Post.STATUS_NORMAL:
            visible_posts = published_posts_visible_to(
                self.request.user,
                Post.objects.select_related("category", "owner"),
            ).exclude(pk=post.pk)
            context['previous_post'] = (
                visible_posts.filter(created_time__lt=post.created_time)
                .order_by('-created_time')
                .first()
            )
            context['next_post'] = (
                visible_posts.filter(created_time__gt=post.created_time)
                .order_by('created_time')
                .first()
            )
        if len(revisions) > 1:
            context['comparison_from_version'] = revisions[-1].version
            context['comparison_to_version'] = revisions[0].version
        return context

    def handle_visit(self):

        if self.object.status != Post.STATUS_NORMAL:
            return

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
    queryset = Post.get_normal_posts().select_related("owner", "owner__profile", "category")
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
        context["stream_start_index"] = context["page_obj"].start_index()
        if context["is_paginated"]:
            context["stream_pagination"] = self.get_stream_pagination(
                context["page_obj"]
            )
        return context


class PostArchiveView(CommonViewMixin, ListView):
    """按年月展示公开且已发布的文章，不暴露 Board 内部内容。"""

    template_name = "pages/blog/archive.html"
    context_object_name = "post_list"
    queryset = Post.publicly_visible_posts().select_related(
        "owner",
        "owner__profile",
        "category",
    )

    def get_queryset(self):
        return super().get_queryset().order_by("-created_time", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        posts = list(context["post_list"])
        groups = []
        start_index = 1

        def month_key(post):
            published_at = timezone.localtime(post.created_time)
            return published_at.year, published_at.month

        for (year, month), month_posts in groupby(posts, key=month_key):
            grouped_posts = list(month_posts)
            groups.append(
                {
                    "year": year,
                    "month": month,
                    "anchor": f"archive-{year}-{month:02d}",
                    "posts": grouped_posts,
                    "count": len(grouped_posts),
                    "start_index": start_index,
                }
            )
            start_index += len(grouped_posts)

        context["archive_groups"] = groups
        context["archive_count"] = len(posts)
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
        self.object = commit_post_form(
            form=form,
            editor=self.request.user,
            change_type='major',
            edit_summary=form.cleaned_data.get('edit_summary', '') or '初始发布',
            expected_revision_id=None,
        )
        logger.info(f"Post 创建: post_id={self.object.id} slug={self.object.slug} "
                    f"user={self.request.user.id} category_id={self.object.category_id}")
        messages.success(
            self.request,
            "提交成功。文章已保存为草稿，审核前仅你本人可见。",
        )
        clear_page_caches()
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        logger.warning(f"Post 创建表单失败: user={self.request.user.id} "
                       f"errors={form.errors}")
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse('Blogs:post_detail', kwargs={'slug': self.object.slug})


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
        change_type = form.cleaned_data.get('change_type') or 'minor'
        edit_summary = form.cleaned_data.get('edit_summary', '')
        try:
            self.object = commit_post_form(
                form=form,
                editor=self.request.user,
                change_type=change_type,
                edit_summary=edit_summary,
                expected_revision_id=form.cleaned_data.get('base_revision_id'),
            )
        except RevisionConflict as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        changed = []
        if previous.title != self.object.title:
            changed.append("title")
        if previous.content != self.object.content:
            changed.append("content")
        logger.info(f"Post 编辑: post_id={self.object.id} slug={self.object.slug} "
                    f"user={self.request.user.id} changed={changed}")
        messages.success(self.request, "保存成功。")
        clear_page_caches()
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        logger.warning(f"Post 编辑表单失败: post_id={self.object.id} "
                       f"user={self.request.user.id} errors={form.errors}")
        return super().form_invalid(form)

    def get_success_url(self):
        if self.object.owner_id == self.request.user.pk:
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
    post = get_object_or_404(Post, slug=slug)
    if not can_view_post_detail(request.user, post):
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
    """Compare any two ordered revisions visible under the Post's Policy."""
    from .revisions import (
        build_structured_diff,
        render_diff as compute_diff,
        render_structured_diff,
    )

    post = get_object_or_404(Post, slug=slug)
    if not can_view_post_detail(request.user, post):
        raise Http404("文章不存在")
    from_ver = request.GET.get('from', '')
    to_ver = request.GET.get('to', '')
    mode = request.GET.get('mode', 'split')

    if mode not in {'split', 'inline', 'stats'}:
        return HttpResponse('Diff 展示模式无效', status=400)

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

    if (rev_from.major, rev_from.minor) > (rev_to.major, rev_to.minor):
        return HttpResponse('起始版本必须早于结束版本', status=400)

    # 相邻版本复用写入时预计算的 R3 数据；任意版本按请求即时构建。
    prev = _get_adjacent_previous(post, rev_to)
    is_adjacent = bool(prev and prev.pk == rev_from.pk)
    diff_html = None
    if is_adjacent and rev_to.diff_structured:
        try:
            diff_html = render_structured_diff(rev_to.diff_structured, mode=mode)
        except ValueError:
            pass

    if diff_html is None and is_adjacent and mode == 'split' and rev_to.diff_from_previous:
        diff_html = rev_to.diff_from_previous

    if diff_html is None:
        diff_data = build_structured_diff(
            rev_from.content, rev_to.content, from_ver, to_ver,
        )
        try:
            diff_html = render_structured_diff(diff_data, mode=mode)
        except ValueError:
            diff_html = compute_diff(
                rev_from.content, rev_to.content, from_ver, to_ver,
            )

    return render(request, 'pages/blog/_revision_diff.html', {
        'post': post,
        'diff_html': diff_html,
        'from_version': from_ver,
        'to_version': to_ver,
        'from_title': rev_from.title,
        'to_title': rev_to.title,
        'diff_mode': mode,
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
