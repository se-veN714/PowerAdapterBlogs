def can_view_security_operations(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and (
            getattr(user, "is_superuser", False)
            or user.has_perm("security.view_audit_log")
        )
    )


def can_run_integrity_audit(user) -> bool:
    return bool(
        can_view_security_operations(user)
        and (
            getattr(user, "is_superuser", False)
            or user.has_perm("security.run_integrity_audit")
        )
    )
