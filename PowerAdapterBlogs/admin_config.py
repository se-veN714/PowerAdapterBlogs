"""Django admin application configuration."""

from django.contrib.admin.apps import AdminConfig


class SuperuserAdminConfig(AdminConfig):
    """Install the project's superuser-only default admin site."""

    default_site = "PowerAdapterBlogs.admin_site.SuperuserAdminSite"
