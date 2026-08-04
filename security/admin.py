from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.safestring import mark_safe

from security.models import SecureLogEntry
from security.services import audit_secure_log_entries
from PowerAdapterBlogs.base_admin import DashboardAdminMixin

# Register your models here.
admin.site.register(SecureLogEntry)

class SecureLogEntryAdmin(DashboardAdminMixin, admin.ModelAdmin):
    """Legacy adapter retained for tests; operations now live at /operations/."""
    list_display = ("log_entry", "status_display", "computed_at", "last_verified_at")
    readonly_fields = ("log_entry", "hmac_truncated", "status_display", "computed_at", "last_verified_at")
    exclude = ("is_tampered", "hmac")

    actions = ["audit_selected_logentries"]

    @staticmethod
    def _can_view_audit_log(request):
        user = request.user
        return user.is_active and (
            user.is_superuser or user.has_perm("security.view_audit_log")
        )

    def has_module_permission(self, request):
        return self._can_view_audit_log(request)

    def has_view_permission(self, request, obj=None):
        return self._can_view_audit_log(request)

    def has_change_permission(self, request, obj=None):
        """仅超级管理员可修改完整性记录"""
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        """仅超级管理员可删除完整性记录"""
        return request.user.is_superuser

    def status_display(self, obj):
        if obj.is_tampered:
            return mark_safe(
                '<span title="日志已被篡改" style="color: red; font-size: 1.2em;">&#x274C;</span>'  # ❌
            )
        return mark_safe(
            '<span title="日志完整" style="color: green; font-size: 1.2em;">&#x2705;</span>'  # ✅
        )

    status_display.short_description = "日志状态"

    def hmac_truncated(self, obj):
        """显示前8位+后8位，中间用...省略"""
        full_hmac = obj.hmac
        return f"{full_hmac[:4]}......{full_hmac[-4:]}" if full_hmac else ""

    hmac_truncated.short_description = "HMAC摘要"

    def has_run_integrity_audit_permission(self, request):
        user = request.user
        return user.is_active and (
            user.is_superuser or user.has_perm("security.run_integrity_audit")
        )

    @admin.action(
        description="审计选中的日志完整性",
        permissions=["run_integrity_audit"],
    )
    def audit_selected_logentries(self, request, queryset):
        try:
            result = audit_secure_log_entries(
                actor=request.user,
                entry_ids=queryset.values_list("pk", flat=True)[:101],
            )
        except (PermissionDenied, ValidationError) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            messages.error(request, detail)
        else:
            messages.success(
                request,
                f"审计完成。核验 {result.checked} 条，发现 {result.tampered} 条异常。",
            )

