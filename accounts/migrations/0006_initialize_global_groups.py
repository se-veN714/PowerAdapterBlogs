from django.db import migrations


GROUP_PERMISSIONS = {
    "VerifiedUsers": (
        ("boards", "board", "apply_board_access", "可申请板块权限"),
    ),
    "UserManagers": (
        ("accounts", "myuser", "manage_user_accounts", "可管理用户账号"),
    ),
    "SiteOperators": (
        ("security", "securelogentry", "view_audit_log", "可查看安全审计日志"),
        (
            "security",
            "securelogentry",
            "run_integrity_audit",
            "可运行日志完整性审计",
        ),
    ),
}


def initialize_global_groups(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    MyUser = apps.get_model("accounts", "MyUser")

    groups = {}
    for group_name, permission_specs in GROUP_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        permissions = []
        for app_label, model, codename, name in permission_specs:
            content_type, _ = ContentType.objects.get_or_create(
                app_label=app_label,
                model=model,
            )
            permission, _ = Permission.objects.get_or_create(
                content_type=content_type,
                codename=codename,
                defaults={"name": name},
            )
            if permission.name != name:
                permission.name = name
                permission.save(update_fields=["name"])
            permissions.append(permission)
        group.permissions.set(permissions)
        groups[group_name] = group

    verified_users = MyUser.objects.filter(is_active=True, is_superuser=False)
    for user in verified_users.iterator():
        user.groups.add(groups["VerifiedUsers"])

    legacy_staff = MyUser.objects.filter(
        is_active=True,
        is_staff=True,
        is_superuser=False,
    )
    for user in legacy_staff.iterator():
        user.groups.add(groups["UserManagers"])


def remove_global_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=GROUP_PERMISSIONS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_alter_myuser_options"),
        ("boards", "0003_alter_board_options"),
        ("security", "0004_alter_securelogentry_options"),
    ]

    operations = [
        migrations.RunPython(initialize_global_groups, remove_global_groups),
    ]
