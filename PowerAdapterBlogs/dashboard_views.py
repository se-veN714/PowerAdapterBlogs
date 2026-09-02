"""First-party, read-only views for the Devenir operations dashboard."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from PowerAdapterBlogs.base_admin import has_dashboard_access
from PowerAdapterBlogs.dashboard_context import (
    audit_context,
    comments_context,
    dashboard_page_allowed,
    media_context,
    overview_context,
    posts_context,
    settings_context,
)


def dashboard_access_required(view_func):
    """Keep first-party pages on the same explicit dashboard identity boundary."""

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), "accounts:login")
        if not has_dashboard_access(request.user):
            raise PermissionDenied("当前账号不能进入站长工作台。")
        return view_func(request, *args, **kwargs)

    return wrapped


def _dashboard_view(template_name, context_builder, *, capability):
    @never_cache
    @dashboard_access_required
    def view(request):
        if not dashboard_page_allowed(request.user, capability):
            raise PermissionDenied("当前账号没有此工作台页面的能力。")
        return render(request, template_name, context_builder(request))

    return view


overview = _dashboard_view(
    "pages/dashboard/overview.html", overview_context, capability="overview"
)
posts = _dashboard_view(
    "pages/dashboard/posts.html", posts_context, capability="posts"
)
audit = _dashboard_view(
    "pages/dashboard/audit.html", audit_context, capability="audit"
)
comments = _dashboard_view(
    "pages/dashboard/comments.html", comments_context, capability="comments"
)
media = _dashboard_view(
    "pages/dashboard/media.html", media_context, capability="media"
)
settings = _dashboard_view(
    "pages/dashboard/settings.html", settings_context, capability="settings"
)
