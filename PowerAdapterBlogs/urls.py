"""
URL configuration for PowerAdapterBlogs project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
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
from Blogs.sitemap import PostSitemap
from Blogs.views import IndexView
from config.views import LinkListView
from .cus_site import custom_site

urlpatterns = [
    path("super_admin/", admin.site.urls, name="super_admin"),
    # dashboard
    path("dashboard/", custom_site.urls, name="dashboard"),
    # dal
    path("category-autocomplete/",CategoryAutocomplete.as_view(),name="category-autocomplete"),
    path("tag-autocomplete/",TagAutocomplete.as_view(),name="tag-autocomplete"),
    # Homepage
    path("", IndexView.as_view(), name="index"),
    path("Blogs/", include(("Blogs.urls", "Blogs"), namespace="blogs")),
    # LinksPage
    path("links/", LinkListView.as_view(), name="links"),
    # sitemap
    path(
        "sitemap.xml/", cache_page(60 * 60)(sitemaps_views.sitemap),
        {'sitemaps': {'posts': PostSitemap}}, name="sitemap")
    ,
    # accounts
    path('accounts/', include(('accounts.urls', 'accounts'), namespace='accounts')),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path("__debug__/", include(debug_toolbar.urls)),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
