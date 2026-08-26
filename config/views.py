from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse
from django.template import loader
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_safe
from django.views.generic import ListView, TemplateView

from Blogs.views import CommonViewMixin
from PowerAdapterBlogs.public_urls import public_absolute_url
from .models import Link


# Create your views here.
class LinkListView(CommonViewMixin, ListView):
    queryset = Link.objects.filter(status=Link.STATUS_NORMAL)
    template_name = 'pages/links.html'
    context_object_name = 'link_list'


class AboutView(TemplateView):
    template_name = "pages/site/about.html"


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


def _error_response(status_code):
    template = loader.get_template("error.html")
    content = template.render({"error_code": status_code})
    return HttpResponse(content, status=status_code)


def page_not_found(request, exception):
    return _error_response(404)


def server_error(request):
    return _error_response(500)
