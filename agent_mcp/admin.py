from django.contrib import admin, messages
from .models import Connection
from .oauth import revoke_connection


@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ('application', 'user', 'created_at', 'expires_at', 'last_used_at', 'revoked_at')
    list_filter = ('revoked_at', 'expires_at')
    readonly_fields = ('family', 'application', 'user', 'scopes', 'created_at', 'expires_at', 'last_used_at', 'revoked_at')
    actions = ('revoke_selected', 'revoke_all_for_users')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    @admin.action(description='撤销选中的 MCP 连接', permissions=['change'])
    def revoke_selected(self, request, queryset):
        for connection in queryset:
            revoke_connection(connection, request.user, 'agent.mcp.admin_revoked')
        messages.success(request, '选中的 MCP 连接及刷新令牌已撤销。')

    @admin.action(description='撤销选中账号的全部 MCP 连接', permissions=['change'])
    def revoke_all_for_users(self, request, queryset):
        for connection in Connection.objects.filter(user_id__in=queryset.values('user_id'), revoked_at__isnull=True):
            revoke_connection(connection, request.user, 'agent.mcp.admin_revoked')
        messages.success(request, '选中账号的全部 MCP 连接已撤销。')
