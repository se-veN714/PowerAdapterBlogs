from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Post, Category, Tag


# Register your models here.
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'is_nav', 'created_time', 'owner')
    field = ('name', 'status', 'is_nav')

    def save_model(self, request, obj, form, change):
        obj.owner = request.user
        return super(CategoryAdmin, self).save_model(request, obj, form, change)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'created_time')
    field = ('name', 'status')

    def save_model(self, request, obj, form, change):
        obj.owner = request.user
        return super(TagAdmin, self).save_model(request, obj, form, change)


class Category_Owner_filter(admin.SimpleListFilter):
    """
    自定义过滤去只展示当前用户分类
    """
    title = "分类过滤器"
    parameter_name = "owner_category"

    def lookups(self, request, queryset):
        return Category.objects.filter(owner=request.user).values_list("id", 'name', flat=True)

    def queryset(self, request, queryset):
        category_id = self.value()
        if category_id:
            return queryset.filter(category_id=category_id)
        return queryset


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'category', 'status',
        'created_time', 'owner'
    ]
    list_display_links = []

    list_filter = ['category', ]
    search_fields = ['title', 'category__name']
    actions_on_top = True
    actions_on_bottom = True

    def operator(self, obj):
        return format_html(
            '<a href="{}">{编辑}</a>',
            reverse('admin:blog_post_change', args=(obj.id,))
        )

    def post_count(self, obj):
        return obj.post_set.count()

    post_count.short_description = "文章数量"
    operator.short_description = "操作"

    def save_model(self, request, obj, form, change):
        obj.owner = request.user
        return super(PostAdmin, self).save_model(request, obj, form, change)
