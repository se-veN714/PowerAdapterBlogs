"""
博客应用的模型定义
改模块定义了博客的数据类型，包括博客文章、分类、标签等。

Article:博客文章
Category:博客文章的分类模型，用于分类博客文章。
"""
from django.db import models


# Create your models here.
class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    add_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = self.name.replace(' ', '-').lower()
        super().save(*args, **kwargs)


    class Meta:
        ordering = ['-add_time']


class Article(models.Model):
    # 基本信息字段
    title = models.CharField(max_length=100)
    content = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='articles')
    blog_language = models.CharField(max_length=10, default='CN')
    blog_cover = models.ImageField(upload_to='images/', null=True, blank=True)

    # 时间戳及链接字段
    add_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)
    slug = models.SlugField(max_length=100, unique=True)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.slug = self.title.replace(' ', '-').lower()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-add_time']

