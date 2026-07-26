from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib import messages

from .forms import AccountInvitationCreationForm
from .models import AccountInvitation, MyUser, UserProfile
from .services import issue_account_invitation

from PowerAdapterBlogs.cus_site import custom_site
from PowerAdapterBlogs.base_admin import DashboardAdminMixin


class MyUserAdmin(UserAdmin):
    model = MyUser
    add_form = AccountInvitationCreationForm
    list_display = ('username', 'email', 'is_active', 'is_reviewer',
                    'is_dashboard_user', 'is_superuser')
    list_filter = ('is_active', 'is_reviewer', 'is_dashboard_user', 'is_superuser')
    ordering = ('date_joined',)

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('证书信息', {'fields': ('cert_sn', 'cert_subject_dn', 'is_cert_verified')}),
        ('权限', {'fields': (
            'is_active', 'is_reviewer', 'is_dashboard_user',
            'is_superuser', 'groups', 'user_permissions',
        )}),
        ('其他信息', {'fields': ('last_login',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'description': '账号将保持未激活；系统会向该邮箱发送一次性密码设置邀请。',
            'fields': ('username', 'email', 'password')}
         ),
    )

    actions = ("resend_account_invitation",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            issue_account_invitation(obj, created_by=request.user)

    @admin.action(description="重新发送账号邀请")
    def resend_account_invitation(self, request, queryset):
        sent = 0
        skipped = 0
        for user in queryset:
            if user.is_active:
                skipped += 1
                continue
            issue_account_invitation(user, created_by=request.user)
            sent += 1
        if sent:
            self.message_user(request, f"已为 {sent} 个未激活账号重新生成邀请。")
        if skipped:
            self.message_user(
                request,
                f"跳过 {skipped} 个已激活账号。",
                level=messages.WARNING,
            )

    def get_readonly_fields(self, request, obj=None):
        """
        权限颗粒化：非 superuser 仅可编辑 is_active（用户启停）。
        is_reviewer 由 superuser 在 /super_admin/ 中授权。
        """
        if request.user.is_superuser:
            return self.readonly_fields
        model_fields = {f.name for f in self.model._meta.fields}
        m2m_fields = {'groups', 'user_permissions'}
        all_fields = model_fields | m2m_fields
        all_fields.discard('is_active')
        return list(all_fields)

    def get_fieldsets(self, request, obj=None):
        """
        非 superuser：仅显示用户审核视图。
        superuser：完整 fieldsets（含 reviewer 授权）。
        """
        if request.user.is_superuser:
            return self.fieldsets
        return (
            ('用户审核', {'fields': ('username', 'email', 'is_active')}),
        )

    def has_change_permission(self, request, obj=None):
        """dashboard 用户可进入修改页面（非 superuser 字段受限）"""
        return request.user.is_dashboard_user

    def has_delete_permission(self, request, obj=None):
        """仅 superuser 可删除用户"""
        return request.user.is_superuser

    def has_add_permission(self, request):
        """仅 superuser 可新增用户"""
        return request.user.is_superuser

    def save_related(self, request, form, formsets, change):
        """
        非 superuser 修改用户时，禁止修改 M2M 关系（groups、user_permissions）。

        MyUser.save() 保护了标量字段（含 is_reviewer），
        但 M2M 在 save() 之后才提交，需要在此处拦截。
        """
        if not request.user.is_superuser and change:
            return  # 跳过 M2M 保存，仅提交 scalar 字段变更
        super().save_related(request, form, formsets, change)


# === 注册到默认 admin.site（/super_admin/，superuser 全权限） ===
try:
    admin.site.unregister(MyUser)
except admin.sites.NotRegistered:
    pass
admin.site.register(MyUser, MyUserAdmin)


# === 注册到 custom_site（/dashboard/，dashboard 用户仅审核 is_active） ===
@admin.register(MyUser, site=custom_site)
class CusMyUserAdmin(DashboardAdminMixin, MyUserAdmin):
    """Account management for superusers and the ``UserManagers`` group."""

    @staticmethod
    def _can_manage_accounts(request):
        user = request.user
        return user.is_active and (
            user.is_superuser or user.has_perm("accounts.manage_user_accounts")
        )

    def has_module_permission(self, request):
        """Board dashboard access must not imply global account management."""
        return self._can_manage_accounts(request)

    def has_view_permission(self, request, obj=None):
        if not self._can_manage_accounts(request):
            return False
        return obj is None or request.user.is_superuser or not obj.is_superuser

    def has_change_permission(self, request, obj=None):
        if not self._can_manage_accounts(request):
            return False
        return obj is None or request.user.is_superuser or not obj.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(is_superuser=False)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("resend_account_invitation", None)
        return actions

    def get_readonly_fields(self, request, obj=None):
        """The permission methods reject non-superusers before form rendering."""
        return super().get_readonly_fields(request, obj)


@admin.register(AccountInvitation)
class AccountInvitationAdmin(admin.ModelAdmin):
    list_display = ("user", "created_by", "created_at", "expires_at", "sent_at", "accepted_at")
    readonly_fields = (
        "user", "created_by", "token_digest", "created_at", "expires_at", "sent_at", "accepted_at"
    )
    search_fields = ("user__username", "user__email")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "is_public", "updated_at")
    list_filter = ("is_public",)
    search_fields = ("user__username", "display_name")
    readonly_fields = ("updated_at",)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
