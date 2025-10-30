from django.db import models
from django.utils.translation import gettext_lazy as _

from Blogs.models import Post


# Create your models here.
class Comment(models.Model):
    """
    comment model
    """
    class Status(models.IntegerChoices):
        PENDING = "0", _("待审核")
        PUBLISHED = "1", _("已发布")
        REJECTED = "2", _("已拒绝")
        DELETED = "3", _("已删除")


    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments', verbose_name="关联文章",default=1)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies',
                               verbose_name="父评论")

    content = models.TextField(max_length=2000, verbose_name="评论内容")

    nickname = models.CharField(max_length=50, blank=True, null=False, verbose_name="昵称")
    email = models.EmailField(blank=True, null=True, verbose_name="邮箱")
    status = models.PositiveIntegerField(default=Status.PENDING, choices=Status.choices, verbose_name="状态")
    created_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = verbose_name_plural = "评论"
        ordering = ['created_time']

    def __str__(self):
        return f"{self.nickname}: {self.content[:20]}"

    @classmethod
    def get_by_target(cls, post):
        """
        get comment by target post
        :param post: model post instance
        :return: all comments that belong to target post
        """
        return cls.objects.filter(
            post=post,
            parent__isnull=True,
            status=cls.Status.PUBLISHED,
        ).order_by('-created_time')
