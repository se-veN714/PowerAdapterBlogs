from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "security"

    def ready(self):
        from security.admin_audit import install_admin_log_actions_hook

        install_admin_log_actions_hook()
        import security.signals  # noqa: F401
