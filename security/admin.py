from django.conf import settings
from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html

from PowerAdapterBlogs.cus_site import custom_site
from security.models import SecureLogEntry, CommentEventLog

# Register your models here.
admin.site.register(SecureLogEntry)
admin.site.register(CommentEventLog)


@admin.register(SecureLogEntry, site=custom_site)
class SecureLogEntryAdmin(admin.ModelAdmin):
    list_display = ("log_entry", "status_display", "computed_at", "last_verified_at")
    readonly_fields = ("log_entry", "hmac_truncated", "status_display", "computed_at", "last_verified_at")
    exclude = ("is_tampered", "hmac")

    actions = ["audit_selected_logentries"]

    def status_display(self, obj):
        if obj.is_tampered:
            return format_html(
                '<span title="日志已被篡改" style="color: red; font-size: 1.2em;">&#x274C;</span>'  # ❌
            )
        return format_html(
            '<span title="日志完整" style="color: green; font-size: 1.2em;">&#x2705;</span>'  # ✅
        )

    status_display.short_description = "日志状态"

    def hmac_truncated(self, obj):
        """显示前8位+后8位，中间用...省略"""
        full_hmac = obj.hmac
        return f"{full_hmac[:4]}......{full_hmac[-4:]}" if full_hmac else ""

    hmac_truncated.short_description = "HMAC摘要"

    @admin.action(description="审计选中的日志完整性")
    def audit_selected_logentries(self, request, queryset):
        secret_key = ""
        try:
            secret_key = settings.LOG_HMAC_KEY
            tampered_count = 0

            for entry in queryset.select_related("log_entry"):
                if SecureLogEntry.audit(entry, secret_key):
                    tampered_count += 1

            messages.success(request, f"审计完成。发现 {tampered_count} 条被篡改的日志。")
        finally:
            # 简单内存清理
            if 'secret_key' in locals():
                secret_key = b"\x00" * len(secret_key)
                del secret_key
            print("审计结束")


@admin.register(CommentEventLog, site=custom_site)
class CommentEventLogAdmin(admin.ModelAdmin):
    list_display = ("comment", "action", "ip_address", "user_agent", "referrer", "url_path", "chain_head_key",)
    readonly_fields = ("comment", "action", "action_at", "ip_address", "user_agent", "referrer", "url_path",
                       "client_fingerprint", "comment_snapshot", "hmac_truncated", "pre_hmac_truncated", "chain_head_key",
                       "masked_ip")

    def hmac_truncated(self, obj):
        """显示前8位+后8位，中间用...省略"""
        full_hmac = obj.hmac
        return f"{full_hmac[:4]}......{full_hmac[-4:]}" if full_hmac else ""

    def pre_hmac_truncated(self,obj):
        full_hmac = obj.pre_hmac
        return f"{full_hmac[:4]}......{full_hmac[-4:]}" if full_hmac else ""

    hmac_truncated.short_description = "HMAC摘要"
    pre_hmac_truncated.short_description = "前HMAC摘要"