from django.conf import settings
from django.db import models
from django.template.loader import render_to_string
import uuid


# Create your models here.
class Link(models.Model):
    STATUS_NORMAL = 1
    STATUS_DELETE = 0
    STATUS_CHOICES = (
        (STATUS_NORMAL, '正常'),
        (STATUS_DELETE, '删除'),
    )

    title = models.CharField(max_length=50, verbose_name="标题")
    href = models.URLField(verbose_name="链接")
    status = models.PositiveIntegerField(default=STATUS_NORMAL, choices=STATUS_CHOICES, verbose_name="状态")
    weight = models.PositiveIntegerField(default=1, choices=zip(range(1, 6), range(1, 6)),
                                         verbose_name="权重", help_text="权重高展示顺序靠前")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="作者")
    created_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = verbose_name_plural = "友链"


class SideBar(models.Model):
    STATUS_SHOW = 1
    STATUS_HIDE = 0
    STATUS_ITEMS = (
        (STATUS_SHOW, "展示"),
        (STATUS_HIDE, "隐藏"),
    )
    DISPLAY_HTML = 1
    DISPLAY_LATEST = 2
    DISPLAY_HOT = 3
    DISPLAY_COMMENT = 4
    SIDE_TYPE = (
        (DISPLAY_HTML, "HTML"),
        (DISPLAY_LATEST, "最新文章"),
        (DISPLAY_HOT, "最热文章"),
        (DISPLAY_COMMENT, "最近评论")
    )

    title = models.CharField(max_length=50, verbose_name="标题")
    display_type = models.PositiveIntegerField(default=1, choices=SIDE_TYPE, verbose_name="展示类型")
    content = models.CharField(max_length=500, blank=True, verbose_name="内容",
                               help_text="若设置类型非 HTML 类型，可为空")
    status = models.PositiveIntegerField(default=STATUS_SHOW, choices=STATUS_ITEMS, verbose_name="状态")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="作者")
    created_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = verbose_name_plural = "侧边栏"

    @classmethod
    def get_sidebars(cls):
        return cls.objects.filter(status=SideBar.STATUS_SHOW)

    @property
    def content_html(self):
        """
        直接渲染模板
        :return: 根据类型渲染内容
        """
        from Blogs.models import Post  # 避免循环引用
        from comment.models import Comment

        content_result = ''
        if self.display_type == self.DISPLAY_HTML:
            content_result = self.content
        elif self.display_type == self.DISPLAY_LATEST:
            context = {
                'posts': Post.latest_posts(with_related=False),
            }
            content_result = render_to_string("pages/config/sidebar_posts.html",context)
        elif self.display_type == self.DISPLAY_HOT:
            context = {
                'posts': Post.hot_posts(with_related=False),
            }
            content_result = render_to_string("pages/config/sidebar_posts.html",context)
        elif self.display_type == self.DISPLAY_COMMENT:
            context = {
                'comments': Comment.objects.filter(status=Comment.Status.PUBLISHED)[:5]
            }
            content_result = render_to_string("pages/config/sidebar_comments.html",context)

        return content_result


class ContentReport(models.Model):
    """Public complaint/report receipt with a privacy-minimized tracking view."""

    class Category(models.TextChoices):
        ILLEGAL_HARMFUL = "illegal_harmful", "违法或不良信息"
        INFRINGEMENT = "infringement", "侵权"
        PRIVACY = "privacy", "隐私或个人信息"
        SPAM = "spam", "垃圾信息或骚扰"
        APPEAL = "appeal", "内容处置申诉"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        PENDING = "pending", "待受理"
        REVIEWING = "reviewing", "处理中"
        RESOLVED = "resolved", "已处理"
        REJECTED = "rejected", "不予处理"

    reference = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name="受理编号",
    )
    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        verbose_name="问题类型",
    )
    target_path = models.CharField(max_length=500, blank=True, verbose_name="本站位置")
    description = models.TextField(max_length=2000, verbose_name="问题说明")
    contact_email = models.EmailField(blank=True, verbose_name="联系邮箱")
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_content_reports",
        verbose_name="提交账号",
    )
    source_ip_digest = models.CharField(
        max_length=64,
        editable=False,
        verbose_name="来源地址摘要",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="处理状态",
    )
    internal_note = models.TextField(blank=True, verbose_name="内部处理记录")
    public_response = models.TextField(blank=True, verbose_name="公开处理反馈")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="提交时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name="处理完成时间",
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "投诉举报"
        verbose_name_plural = "投诉举报"

    def __str__(self):
        return f"{self.reference} · {self.get_status_display()}"
