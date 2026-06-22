from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import MyUser

from PowerAdapterBlogs.cus_site import custom_site
from PowerAdapterBlogs.base_admin import DashboardAdminMixin


class MyUserAdmin(UserAdmin):
    model = MyUser
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
            'fields': ('username', 'email', 'password1', 'password2',
                       'is_active', 'is_reviewer', 'is_dashboard_user', 'is_superuser')}
         ),
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
    """custom_site 版本，最小权限：只能启停非超管账号"""

    def has_change_permission(self, request, obj=None):
        """非 superuser 不能编辑 superuser 账号（避免 dashboard 用户禁用超管）"""
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """dashboard 用户无删除权限"""
        return False

    def get_readonly_fields(self, request, obj=None):
        """双重保险：dashboard 用户面对 superuser 时全字段只读"""
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return [f.name for f in self.model._meta.fields]
        return super().get_readonly_fields(request, obj)
