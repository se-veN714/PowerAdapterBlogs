from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404

from .form import CommentForm
from Blogs.models import Post


# Create your views here.
class CommentView(TemplateView):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        post_id = kwargs.get('pk')
        post = get_object_or_404(Post, id=post_id)

        form = CommentForm(request.POST)

        if form.is_valid():
            instance = form.save(commit=False)
            instance.post = post
            print()

            instance.save()

            return JsonResponse({
                'success': True,
                'html': render_to_string('comment/item.html', {'comment': instance}),
                'message': '评论提交成功!',
            })
        else:
            # 将错误信息格式化为字段: [错误消息] 的字典
            errors = {field: [error for error in error_list]
                      for field, error_list in form.errors.items()}

            return JsonResponse({
                'success': False,
                'message': '请修正以下错误',
                'errors': errors
            }, status=400)
