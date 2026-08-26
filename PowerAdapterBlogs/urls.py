"""
URL configuration for PowerAdapterBlogs project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps import views as sitemaps_views
from django.urls import path, include
from django.views.decorators.cache import cache_page

from Blogs.autocomplete import CategoryAutocomplete, TagAutocomplete
from Blogs.feed import PublicPostAtomFeed, PublicPostFeed
from Blogs.sitemap import PostSitemap
from Blogs.views import IndexView
from boards.amap_proxy import amap_service_proxy
from config.views import AboutView, LinkListView, PrivacyView, robots_txt, security_txt
from .cus_site import custom_site

urlpatterns = [
    path("_AMapService/<path:resource>", amap_service_proxy, name="amap-service"),
    path("super_admin/", admin.site.urls, name="super_admin"),
    # dashboard
    path(
        "dashboard/memberships/",
        include("boards.dashboard_urls"),
    ),
    path("dashboard/compatibility/", custom_site.urls),
    path(
        "dashboard/",
        include(("PowerAdapterBlogs.dashboard_urls", "dashboard"), namespace="dashboard"),
    ),
    # dal
    path(
        "category-autocomplete/",
        CategoryAutocomplete.as_view(),
        name="category-autocomplete",
    ),
    path("tag-autocomplete/", TagAutocomplete.as_view(), name="tag-autocomplete"),
    # Homepage
    path("", IndexView.as_view(), name="index"),
    path("Blogs/", include(("Blogs.urls", "Blogs"), namespace="blogs")),
    path("feed/", PublicPostFeed(), name="feed"),
    path("feed/atom/", PublicPostAtomFeed(), name="atom-feed"),
    # LinksPage
    path("links/", LinkListView.as_view(), name="links"),
    path("about/", AboutView.as_view(), name="about"),
    path("privacy/", PrivacyView.as_view(), name="privacy"),
    path("robots.txt", robots_txt, name="robots"),
    path(".well-known/security.txt", security_txt, name="security-txt"),
    # sitemap
    path(
        "sitemap.xml/",
        cache_page(60 * 60)(sitemaps_views.sitemap),
        {"sitemaps": {"posts": PostSitemap}},
        name="sitemap",
    ),
    # accounts
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("boards/", include(("boards.urls", "boards"), namespace="boards")),
    path("review/", include(("moderation.urls", "moderation"), namespace="moderation")),
    path(
        "operations/",
        include(("operations.urls", "operations"), namespace="operations"),
    ),
    path("security/", include(("security.urls", "security"), namespace="security")),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [
        path("__debug__/", include(debug_toolbar.urls)),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


handler404 = "config.views.page_not_found"
handler500 = "config.views.server_error"
