"""Boards 应用的 Django Admin 注册。

Board 与 Board Index 内容模型全部注册到默认 admin.site（= SuperuserAdminSite，
/super_admin/），仅 superuser 可维护。dashboard (/dashboard/) 不再暴露任何板块
内容管理入口。BoardAccessRequest 保留双注册（dashboard 供板块 Manager 审核本板
申请，super_admin 供站长全局审核）。
"""

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.html import format_html

from PowerAdapterBlogs.cus_site import custom_site
from boards.models import (
    AppleRecord,
    Board,
    BoardAccessRequest,
    BoardMembership,
    CodingExperiment,
    CodingPrinciple,
    CodingProject,
    SkateClip,
    SkateHomie,
    SpotifyRecord,
)
from boards.policies import (
    can_access_board_admin,
    can_manage_board_members,
)
from boards.services import (
    approve_board_access_request,
    reject_board_access_request,
)


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    """首页板块管理：仅 superuser（站点结构与前端代码绑定，不可委托给 dashboard）。

    行内编辑排序、颜色、启用状态，方便快速调整首页布局。
    """

    list_display = [
        "sort_order",
        "name",
        "glitch_color_preview",
        "category",
        "is_active",
        "updated_at",
    ]
    list_display_links = ["name"]
    list_editable = ["sort_order"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug", "keywords"]
    ordering = ["sort_order"]

    fieldsets = (
        (
            "基本信息",
            {
                "fields": ("slug", "name", "sort_order", "is_active"),
            },
        ),
        (
            "内容",
            {
                "fields": ("description",),
            },
        ),
        (
            "视觉效果",
            {
                "fields": ("glitch_color", "keywords"),
            },
        ),
        (
            "关联",
            {
                "fields": ("category",),
            },
        ),
    )

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    @admin.display(description="Glitch 颜色")
    def glitch_color_preview(self, obj):
        """在列表中展示颜色预览色块。"""
        return format_html(
            '<span style="display:inline-block;width:20px;height:20px;'
            "background:{};border-radius:3px;"
            'border:1px solid rgba(255,255,255,0.15);"></span> '
            "<code>{}</code>",
            obj.glitch_color,
            obj.glitch_color,
        )


@admin.register(BoardMembership)
class BoardMembershipObservationAdmin(admin.ModelAdmin):
    """Super-admin-only, read-only observation of Board memberships.

    Membership writes will be introduced through the reviewed approval flow in
    a later accounts_linear stage. Keeping this view off ``custom_site`` avoids
    exposing cross-Board membership data before scoped querysets exist.
    """

    list_display = ["board", "user", "role", "is_active", "created_by", "created_at"]
    list_filter = ["board", "role", "is_active"]
    search_fields = ["board__name", "board__slug", "user__username", "user__email"]
    list_select_related = ["board", "user", "created_by"]
    ordering = ["board__sort_order", "user__username"]
    readonly_fields = [
        "board",
        "user",
        "role",
        "is_active",
        "created_by",
        "created_at",
    ]

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class BoardAccessRequestAdminBase(admin.ModelAdmin):
    list_display = [
        "board",
        "applicant",
        "requested_role",
        "status",
        "previous_role",
        "reviewed_by",
        "created_at",
        "reviewed_at",
    ]
    list_filter = ["status", "requested_role", "board"]
    search_fields = ["board__name", "applicant__username", "applicant__email"]
    list_select_related = ["board", "applicant", "reviewed_by"]
    readonly_fields = [
        "board",
        "applicant",
        "requested_role",
        "reason",
        "status",
        "previous_role",
        "reviewed_by",
        "decision_note",
        "created_at",
        "reviewed_at",
    ]
    actions = ["approve_requests", "reject_requests"]

    def has_module_permission(self, request):
        return can_access_board_admin(request.user)

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return can_access_board_admin(request.user)
        return can_manage_board_members(request.user, obj.board)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_review_permission(self, request):
        return can_access_board_admin(request.user)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_active and request.user.is_superuser:
            return queryset
        return queryset.filter(
            board__is_active=True,
            board__memberships__user=request.user,
            board__memberships__role=BoardMembership.Role.MANAGER,
            board__memberships__is_active=True,
        ).distinct()

    def _decide(self, request, queryset, *, approve):
        success_count = 0
        for access_request in queryset:
            try:
                service = (
                    approve_board_access_request
                    if approve
                    else reject_board_access_request
                )
                service(access_request=access_request, actor=request.user)
            except (PermissionDenied, ValidationError) as exc:
                detail = (
                    " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                )
                self.message_user(
                    request,
                    f"申请 #{access_request.pk} 未处理：{detail}",
                    level=messages.WARNING,
                )
            else:
                success_count += 1
        if success_count:
            verb = "批准" if approve else "驳回"
            self.message_user(request, f"已{verb} {success_count} 条申请。")

    @admin.action(description="批准选中的板块权限申请", permissions=["review"])
    def approve_requests(self, request, queryset):
        self._decide(request, queryset, approve=True)

    @admin.action(description="驳回选中的板块权限申请", permissions=["review"])
    def reject_requests(self, request, queryset):
        self._decide(request, queryset, approve=False)


class DashboardBoardAccessRequestAdmin(BoardAccessRequestAdminBase):
    """Legacy adapter retained for tests; reviews now live at /review/boards/."""


@admin.register(BoardAccessRequest)
class SystemBoardAccessRequestAdmin(BoardAccessRequestAdminBase):
    """The system admin is already restricted to active superusers."""

    pass


class SuperuserBoardContentAdmin(admin.ModelAdmin):
    """Board Index 内容模型：仅 superuser 可维护（决策 5，无公开投稿）。

    content 模型的 board 由模型类型固定（见 boards.models），不可手动选择，
    因此统一从表单中排除。
    """

    exclude = ("board",)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


@admin.register(SkateHomie)
class SkateHomieAdmin(SuperuserBoardContentAdmin):
    list_display = [
        "node_index",
        "name",
        "call_sign",
        "location",
        "stance",
        "role_label",
        "updated_at",
    ]
    list_filter = ["stance"]
    search_fields = ["name", "call_sign", "location"]
    ordering = ["node_index"]


@admin.register(SkateClip)
class SkateClipAdmin(SuperuserBoardContentAdmin):
    list_display = [
        "order",
        "title",
        "homie",
        "category",
        "spot",
        "status",
        "is_public",
    ]
    list_filter = ["category", "status", "is_public"]
    search_fields = ["title", "spot"]
    ordering = ["order"]


@admin.register(SpotifyRecord)
class SpotifyRecordAdmin(SuperuserBoardContentAdmin):
    list_display = [
        "title",
        "scope",
        "year",
        "month",
        "kind",
        "label",
        "value",
        "display_order",
        "updated_at",
    ]
    list_filter = ["scope", "year", "kind"]
    search_fields = ["title", "label", "value"]
    ordering = ["-year", "-month", "display_order"]


@admin.register(AppleRecord)
class AppleRecordAdmin(SuperuserBoardContentAdmin):
    list_display = [
        "title",
        "scope",
        "year",
        "month",
        "kind",
        "label",
        "value",
        "display_order",
        "updated_at",
    ]
    list_filter = ["scope", "year", "kind"]
    search_fields = ["title", "label", "value"]
    ordering = ["-year", "-month", "display_order"]


@admin.register(CodingProject)
class CodingProjectAdmin(SuperuserBoardContentAdmin):
    list_display = ["index", "name", "year", "status", "is_active", "order"]
    list_filter = ["status", "is_active"]
    search_fields = ["name", "stack"]
    ordering = ["order"]


@admin.register(CodingPrinciple)
class CodingPrincipleAdmin(SuperuserBoardContentAdmin):
    list_display = ["index", "title", "order"]
    search_fields = ["title"]
    ordering = ["order"]


@admin.register(CodingExperiment)
class CodingExperimentAdmin(SuperuserBoardContentAdmin):
    list_display = ["date", "title", "order"]
    search_fields = ["title"]
    ordering = ["-date"]
