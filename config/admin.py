import logging

from django.contrib import admin
from .models import ContentReport, Link, SideBar
from .services import review_content_report
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


@admin.register(ContentReport)
class ContentReportAdmin(admin.ModelAdmin):
    list_display = ("reference", "category", "status", "target_path", "created_at")
    list_filter = ("status", "category", "created_at")
    search_fields = ("reference", "target_path", "description", "contact_email")
    readonly_fields = (
        "reference",
        "submitted_by",
        "source_ip_digest",
        "category",
        "target_path",
        "description",
        "contact_email",
        "created_at",
        "updated_at",
        "resolved_at",
    )
    fields = readonly_fields + ("status", "internal_note", "public_response")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        reviewed = review_content_report(
            actor=request.user,
            report_id=obj.pk,
            status=obj.status,
            internal_note=obj.internal_note,
            public_response=obj.public_response,
        )
        obj.resolved_at = reviewed.resolved_at
        obj.updated_at = reviewed.updated_at
