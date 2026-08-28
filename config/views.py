from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.core.cache import caches
from django.db import connections
from django.http import Http404, HttpResponse
from django.template import loader
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_safe
from django.views.generic import ListView, TemplateView

from Blogs.views import CommonViewMixin
from PowerAdapterBlogs.public_urls import public_absolute_url
from boards.board_index import renderable_boards
from .models import Link


@require_safe
def healthz(request):
    """Dependency-aware container probe without exposing diagnostic details."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        cache = caches["default"]
        # A fixed probe key lets concurrent health checks delete each other's
        # value and report a false outage. Keep every probe isolated.
        token = f"poweradapter-healthz:{uuid4().hex}"
        cache.set(token, "ok", timeout=5)
        if cache.get(token) != "ok":
            raise RuntimeError("cache probe failed")
        cache.delete(token)
    except Exception:
        return HttpResponse(
            "unavailable\n",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    return HttpResponse("ok\n", content_type="text/plain; charset=utf-8")


# Create your views here.
class LinkListView(CommonViewMixin, ListView):
    queryset = Link.objects.filter(status=Link.STATUS_NORMAL)
    template_name = 'pages/links.html'
    context_object_name = 'link_list'


class AboutView(TemplateView):
    template_name = "pages/site/about.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        core_slugs = ("skateboard", "music", "coding")
        context["additional_about_boards"] = renderable_boards().exclude(
            slug__in=core_slugs
        )
        return context


class PrivacyView(TemplateView):
    template_name = "pages/site/privacy.html"


@require_safe
def robots_txt(request):
    lines = (
        "User-agent: *",
        "Allow: /",
        "Disallow: /super_admin/",
        "Disallow: /dashboard/",
        "Disallow: /accounts/invitation/",
        "Disallow: /accounts/settings/",
        "Disallow: /Blogs/img_upload/",
        f"Sitemap: {public_absolute_url(reverse('sitemap'))}",
    )
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


@require_safe
def security_txt(request):
    expires = timezone.now() + timedelta(days=180)
    expires_value = expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    canonical = public_absolute_url(reverse("security-txt"))
    lines = (
        f"Contact: mailto:{settings.SECURITY_CONTACT_EMAIL}",
        f"Expires: {expires_value}",
        "Preferred-Languages: zh, en, ja",
        f"Canonical: {canonical}",
    )
    response = HttpResponse("\n".join(lines) + "\n", content_type="text/plain")
    response["Cache-Control"] = "public, max-age=86400"
    return response


ERROR_VARIANTS = {
    "general": {
        "label": "PowerAdapter",
        "asset": "images/errors/alpha-error-visual-general.webp",
        "process": ("observe(world)", "recover(state)"),
    },
    "skateboard": {
        "label": "Skateboard",
        "asset": "images/errors/alpha-error-visual-skateboard.webp",
        "process": ("read(line)", "rebalance(landing)"),
    },
    "music": {
        "label": "Music",
        "asset": "images/errors/alpha-error-visual-music.webp",
        "process": ("listen(signal)", "resync(track)"),
    },
    "coding": {
        "label": "Coding",
        "asset": "images/errors/alpha-error-visual-coding.webp",
        "process": ("trace(state)", "recover(runtime)"),
    },
}

ERROR_COPY = {
    403: {
        "status": "access denied",
        "message": (
            "This transmission is outside your current clearance.",
            "Return to a permitted route or request the required access.",
        ),
    },
    404: {
        "status": "signal absent",
        "message": (
            "The requested transmission was not found.",
            "It may have moved, expired, or never existed.",
        ),
    },
    500: {
        "status": "system unstable",
        "message": (
            "The render process was interrupted.",
            "The system temporarily lost its balance.",
            "Please retry after a short interval.",
        ),
    },
}


def _error_variant_from_path(path):
    """Resolve a known board from a URL without touching the database."""
    segments = {segment.lower() for segment in path.split("/") if segment}
    for variant in ("skateboard", "music", "coding"):
        if variant in segments:
            return variant
    return "general"


def _error_response(status_code, *, request=None, variant=None):
    if status_code not in ERROR_COPY:
        raise Http404("Unsupported error preview status.")

    resolved_variant = variant or _error_variant_from_path(request.path)
    variant_config = ERROR_VARIANTS.get(resolved_variant)
    if variant_config is None:
        raise Http404("Unknown error page variant.")

    template = loader.get_template("error.html")
    context = {
        "error_code": status_code,
        "error_variant": resolved_variant,
        "error_label": variant_config["label"],
        "error_visual_asset": variant_config["asset"],
        "error_process": variant_config["process"],
        **ERROR_COPY[status_code],
    }
    # Error rendering must not invoke site-wide context processors: the original
    # failure may have happened before authentication or board context exists.
    content = template.render(context)
    response = HttpResponse(content, status=status_code)
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def error_preview(request, variant, status_code):
    """Render a real-status preview so error pages remain directly testable."""
    if not getattr(settings, "ERROR_PREVIEW_ENABLED", False):
        raise Http404("Error previews are disabled outside development.")
    response = _error_response(status_code, request=request, variant=variant)
    response["X-Error-Preview"] = "1"
    return response


def page_not_found(request, exception):
    return _error_response(404, request=request)


def permission_denied(request, exception):
    return _error_response(403, request=request)


def server_error(request):
    return _error_response(500, request=request)
