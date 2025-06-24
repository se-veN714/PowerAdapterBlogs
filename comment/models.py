from django.db import models
from django.contrib.auth.models import User

from Blogs.models import Post


# Create your models here.
class Comment(models.Model):
    STATUS_NORMAL = 1
    STATUS_DELETE = 0
    STATUS_ITEMS = (
        (STATUS_NORMAL, "正常"),
        (STATUS_DELETE, "删除"),
    )

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments', verbose_name="关联文章",default=1)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies',
                               verbose_name="父评论")

    content = models.TextField(max_length=2000, verbose_name="评论内容")

    nickname = models.CharField(max_length=50, blank=True, null=True, verbose_name="昵称")
    email = models.EmailField(blank=True, null=True, verbose_name="邮箱")

    image = models.ImageField(upload_to='comment_images/', blank=True, null=True, verbose_name="附图")

    status = models.PositiveIntegerField(default=STATUS_NORMAL, choices=STATUS_ITEMS, verbose_name="状态")
    created_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = verbose_name_plural = "评论"
        ordering = ['created_time']

    def __str__(self):
        return f"{self.nickname or '匿名'}: {self.content[:20]}"

    @classmethod
    def get_by_target(cls, post):
        return cls.objects.filter(
            post=post,
            parent__isnull=True,
            status=cls.STATUS_NORMAL,
        ).order_by('-created_time')