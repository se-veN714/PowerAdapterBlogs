from django.contrib import admin

from .models import Category, Article


# Register your models here.
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'slug', 'add_time', 'update_time')
    prepopulated_fields = {'slug': ('title',)}
    list_filter = ('category',)
    search_fields = ('title', 'add_time')
