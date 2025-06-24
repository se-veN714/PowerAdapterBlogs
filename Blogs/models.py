"""
博客应用的模型定义
改模块定义了博客的数据类型，包括博客文章、分类、标签等。

Article:博客文章
Category:博客文章的分类模型，用于分类博客文章。
"""
from django.db import models
from django.contrib.auth.models import User


# Create your models here.
class Category(models.Model):
    # 状态字段
    STATUS_NORMAL = 1
    STATUS_DELETE = 0
    STATUS_ITEMS = (
        (STATUS_NORMAL, "正常"),
        (STATUS_DELETE, "删除"),
    )
    # 基本信息字段
    name = models.CharField(max_length=50, verbose_name="名称")
    status = models.PositiveIntegerField(default=STATUS_NORMAL, choices=STATUS_ITEMS, verbose_name="状态")
    is_nav = models.BooleanField(default=False, verbose_name="是否为导航")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="作者")
    created_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = verbose_name_plural = "分类"

    @classmethod
    def get_navs(cls):
        categories = cls.objects.filter(status=cls.STATUS_NORMAL)
        nav_categories = []
        normal_categories = []

        for category in categories:
            if category.is_nav:
                nav_categories.append(category)
            else:
                normal_categories.append(category)

        return {
            "categories": normal_categories,
            "navs": nav_categories,
        }


class Tag(models.Model):
    # 状态字段
    STATUS_NORMAL = 1
    STATUS_DELETE = 0
    STATUS_ITEMS = (
        (STATUS_NORMAL, "正常"),
        (STATUS_DELETE, "删除"),
    )
    # 基本信息字段
    name = models.CharField(max_length=50, verbose_name="名称")
    status = models.PositiveIntegerField(default=STATUS_NORMAL, choices=STATUS_ITEMS, verbose_name="状态")
    is_nav = models.BooleanField(default=False, verbose_name="是否为导航")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="作者")
    created_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = verbose_name_plural = "标签"


class Post(models.Model):
    # 基本信息字段
    STATUS_NORMAL = 1
    STATUS_DELETE = 0
    STATUS_ITEMS = (
        (STATUS_NORMAL, "正常"),
        (STATUS_DELETE, "删除"),
    )

    # 文章基本内容
    title = models.CharField(max_length=255, verbose_name="标题")
    desc = models.CharField(max_length=1024, blank=True, verbose_name="摘要")
    content = models.TextField(verbose_name="正文", help_text="正文必须为 Markdown 格式")
    status = models.PositiveIntegerField(default=STATUS_NORMAL, choices=STATUS_ITEMS, verbose_name="状态")

    # 文章基本信息
    category = models.ForeignKey(Category, on_delete=models.CASCADE, verbose_name="分类")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, verbose_name="标签")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="作者")
    cover = models.ImageField(upload_to='covers/', blank=True, null=True, verbose_name="封面")
    pv = models.PositiveIntegerField(default=1)
    uv = models.PositiveIntegerField(default=1)

    # 文章时间戳
    created_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="上次修改时间")

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = verbose_name_plural = "文章"
        ordering = ['-created_time']

    @staticmethod
    def get_by_tag(tag_id):
        """
        该方法通过 标签id 过滤所需文章
        :param tag_id: 标签id
        :return: 标签文章及其标签
        """
        try:
            tag = Tag.objects.get(id=tag_id)
        except Tag.DoesNotExist:
            tag = None
            posts = None
        else:
            posts = tag.post_set.filter(status=Post.STATUS_NORMAL).select_related("owner", "category")

        return posts, tag

    @staticmethod
    def get_by_category(category_id):
        """
        该方法通过 分类id 过滤所需文章
        :param category_id: 分类id
        :return: 分类文章及其分类
        """
        try:
            category = Category.objects.get(id=category_id)
        except Category.DoesNotExist:
            category = None
            posts = None
        else:
            posts = category.post_set.filter(status=Post.STATUS_NORMAL).select_related("owner", "category")

        return posts, category

    @classmethod
    def get_normal_posts(cls):
        return cls.objects.filter(status=Post.STATUS_NORMAL)

    @classmethod
    def get_by_id(cls, post_id):
        return cls.objects.get(id=post_id)

    @classmethod
    def latest_posts(cls, num=5):
        """
        :return: 返回最近投稿的文章
        """
        return cls.objects.filter(status=cls.STATUS_NORMAL).order_by('-created_time')[:num]

    @classmethod
    def hot_posts(cls):
        """
        :return: 返回最多访问的文章--只返回标题和id
        """
        return cls.objects.filter(status=cls.STATUS_NORMAL).order_by("-pv").only("title", "id")[:3]
