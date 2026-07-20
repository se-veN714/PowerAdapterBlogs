import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.views.generic import TemplateView

from Blogs.models import Post
from boards.policies import can_view_published_post
from comment.form import CommentForm
from comment.models import Comment

logger = logging.getLogger(__name__)


def _comment_rate_key(request):
    client_ip = getattr(request, 'client_ip', request.META.get('REMOTE_ADDR', 'unknown'))
    return f"comment-rate:{request.user.pk}:{client_ip}"


def _consume_comment_quota(request):
    """返回是否允许提交，以及当前窗口剩余秒数。"""
    key = _comment_rate_key(request)
    limit = getattr(settings, 'COMMENT_RATE_LIMIT', 5)
    window = getattr(settings, 'COMMENT_RATE_WINDOW', 60)
    if cache.add(key, 1, timeout=window):
        return True, window
    try:
        attempts = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window)
        attempts = 1
    return attempts <= limit, window


# Create your views here.
class CommentView(LoginRequiredMixin, TemplateView):
    """
    Handles user comment submissions on blog posts.

    This view requires the user to be authenticated before posting a comment.
    It also records a security event log that includes metadata such as IP,
    User-Agent, referrer, and a SM3-based client fingerprint.

    Methods:
        post(request, *args, **kwargs): Handles the comment form submission.
    """
    http_method_names = ['post']
    login_url = '/accounts/login/'  # 可自定义登录页
    redirect_field_name = None  # 禁止302跳转，用于API兼容（返回JSON）

    def handle_no_permission(self):
        """Override to return JSON instead of redirecting."""
        return JsonResponse({
            'success': False,
            'message': '请先登录后再发表评论。',
        }, status=401)

    def post(self, request, *args, **kwargs):
        post_slug = kwargs.get('slug')
        post = get_object_or_404(Post, slug=post_slug, status=Post.STATUS_NORMAL)
        if not can_view_published_post(request.user, post):
            return JsonResponse(
                {'success': False, 'message': '文章不存在。'},
                status=404,
            )

        allowed, retry_after = _consume_comment_quota(request)
        if not allowed:
            logger.warning("Comment 提交限流: post_slug=%s user=%s", post_slug, request.user.id)
            response = JsonResponse({
                'success': False,
                'message': f'提交过于频繁，请在 {retry_after} 秒后重试。',
            }, status=429)
            response['Retry-After'] = str(retry_after)
            return response

        form = CommentForm(request.POST)
        if not form.is_valid():
            errors = {field: [error for error in error_list]
                      for field, error_list in form.errors.items()}
            logger.warning(f"Comment 提交失败: post_slug={post_slug} "
                           f"user={request.user.id if request.user.is_authenticated else 'anon'} "
                           f"errors={form.errors}")
            return JsonResponse({
                'success': False,
                'message': '请修正以下错误',
                'errors': errors
            }, status=400)

        try:
            instance = form.save(commit=False)
            instance.post = post
            instance.user = request.user  # 记录评论者
            instance.save()

            logger.info(f"Comment 提交: comment_id={instance.id} "
                        f"post_slug={post_slug} "
                        f"user={request.user.id if request.user.is_authenticated else 'anon'} "
                        f"nickname={form.cleaned_data.get('nickname', '')[:20]}")
        except Exception as e:
            logger.exception(f"Comment 保存异常: post_slug={post_slug} "
                           f"user={request.user.id if request.user.is_authenticated else 'anon'} "
                           f"error={e}")
            return JsonResponse({
                'success': False,
                'message': '评论保存失败，请稍后重试。',
            }, status=500)

        return JsonResponse({
            'success': True,
            'html': render_to_string(
                'pages/comment/item.html', {'comment': instance}, request=request
            ),
            'message': '评论提交成功!',
        })


class CommentDeleteView(LoginRequiredMixin, TemplateView):
    """评论作者软删除自己的评论；superuser 也可执行。"""

    http_method_names = ['post']
    redirect_field_name = None

    def handle_no_permission(self):
        return JsonResponse({'success': False, 'message': '请先登录。'}, status=401)

    def post(self, request, *args, **kwargs):
        comment = get_object_or_404(Comment, pk=kwargs['pk'])
        if comment.user_id != request.user.id and not request.user.is_superuser:
            return JsonResponse({'success': False, 'message': '无权删除这条评论。'}, status=403)
        comment.status = Comment.Status.DELETED
        comment.save(update_fields=['status'])
        logger.info("Comment 用户删除: comment_id=%s user=%s", comment.id, request.user.id)
        return JsonResponse({'success': True, 'message': '评论已删除。'})
