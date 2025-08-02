from django.contrib import admin

# Register your models here.
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import MyUser

from PowerAdapterBlogs.cus_site import custom_site


@admin.register(MyUser, site=custom_site)
class MyUserAdmin(UserAdmin):
    model = MyUser
    list_display = ('username', 'email', 'is_active', 'is_dashboard_user', 'is_superuser')
    list_filter = ('is_active', 'is_dashboard_user', 'is_superuser')
    readonly_fields = ('username', 'email', 'is_active', 'is_dashboard_user', 'is_superuser')
    ordering = ('date_joined',)

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('证书信息', {'fields': ('cert_sn', 'cert_subject_dn', 'is_cert_verified')}),
        ('权限', {'fields': ('is_active', 'is_dashboard_user', 'is_superuser', 'groups', 'user_permissions')}),
        ('其他信息', {'fields': ('last_login',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'is_active', 'is_dashboard_user', 'is_superuser')}
         ),
    )
