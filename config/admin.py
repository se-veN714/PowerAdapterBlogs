import logging

from django.contrib import admin

from .models import Link, SideBar
from PowerAdapterBlogs.base_admin import BaseOwnerAdmin

logger = logging.getLogger(__name__)


# Register your models here.
@admin.register(Link)
class LinkAdmin(BaseOwnerAdmin):
    list_display = ('title', 'href', 'status', 'weight', 'created_time')
    fields = ('title', 'href', 'status', 'weight')

    def save_model(self, request, obj, form, change):
        if change:
            logger.info(f"Link 修改: link_id={obj.id} title={obj.title} "
                        f"operator={request.user.id}")
        else:
            logger.info(f"Link 创建: link_id={obj.id} title={obj.title} "
                        f"operator={request.user.id}")
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        logger.info(f"Link 删除: link_id={obj.id} title={obj.title} "
                    f"operator={request.user.id}")
        super().delete_model(request, obj)


@admin.register(SideBar)
class SideBarAdmin(BaseOwnerAdmin):
    list_display = ('title', 'display_type', 'content', 'created_time')
    fields = ('title', 'display_type', 'content')

    def save_model(self, request, obj, form, change):
        if change:
            logger.info(f"SideBar 修改: sidebar_id={obj.id} title={obj.title} "
                        f"operator={request.user.id}")
        else:
            logger.info(f"SideBar 创建: sidebar_id={obj.id} title={obj.title} "
                        f"operator={request.user.id}")
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        logger.info(f"SideBar 删除: sidebar_id={obj.id} title={obj.title} "
                    f"operator={request.user.id}")
        super().delete_model(request, obj)
