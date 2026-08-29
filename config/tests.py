from datetime import datetime
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from config.views import server_error


class SiteInformationPageTest(TestCase):
    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
            "sessions": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        }
    )
    def test_healthz_checks_database_and_cache(self):
        response = self.client.get(reverse("healthz"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok\n")

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
            "sessions": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        }
    )
    def test_healthz_uses_an_isolated_cache_key_per_probe(self):
        class RecordingCache:
            def __init__(self):
                self.values = {}
                self.set_keys = []

            def set(self, key, value, timeout):
                self.set_keys.append(key)
                self.values[key] = value

            def get(self, key):
                return self.values.get(key)

            def delete(self, key):
                self.values.pop(key, None)

        cache = RecordingCache()
        with patch("config.views.caches", {"default": cache}):
            first = self.client.get(reverse("healthz"))
            second = self.client.get(reverse("healthz"))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(cache.set_keys), 2)
        self.assertNotEqual(cache.set_keys[0], cache.set_keys[1])

    def test_about_page_is_public_and_explains_three_plus_n_fields(self):
        response = self.client.get(reverse("about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "三个已生成的场域")
        self.assertContains(response, "Something will devenir here")

    def test_privacy_page_is_public_and_documents_retention(self):
        response = self.client.get(reverse("privacy"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "保留周期")
        self.assertContains(response, "10 分钟失效")
        self.assertContains(response, "MongoDB")

    def test_global_navigation_links_about_and_privacy(self):
        response = self.client.get(reverse("about"))

        self.assertContains(response, f'href="{reverse("about")}"')
        self.assertContains(response, f'href="{reverse("privacy")}"')

    def test_public_pages_display_required_regulatory_filing_links(self):
        response = self.client.get(reverse("about"))

        self.assertContains(response, "滇ICP备2025068499号-1")
        self.assertContains(response, 'href="https://beian.miit.gov.cn/"')
        self.assertContains(response, "滇公网安备53010302001568号")
        self.assertContains(
            response,
            'href="https://beian.mps.gov.cn/#/query/webSearch?code=53010302001568"',
        )


@override_settings(DEBUG=False, PUBLIC_SITE_URL="https://blog.example.test")
class PublicSiteMetadataTest(TestCase):
    def test_canonical_and_feed_discovery_use_public_site_configuration(self):
        response = self.client.get(reverse("about"), HTTP_HOST="untrusted.example")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<link rel="canonical" href="https://blog.example.test/about/">',
            html=True,
        )
        self.assertContains(response, 'type="application/rss+xml"')
        self.assertContains(response, 'type="application/atom+xml"')

    def test_robots_blocks_private_surfaces_and_uses_absolute_sitemap(self):
        response = self.client.get(reverse("robots"))
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/plain"))
        self.assertIn("Disallow: /super_admin/", content)
        self.assertIn("Disallow: /dashboard/", content)
        self.assertIn("Disallow: /accounts/invitation/", content)
        self.assertIn("Sitemap: https://blog.example.test/sitemap.xml/", content)

    @override_settings(SECURITY_CONTACT_EMAIL="security@example.test")
    def test_security_txt_is_rfc9116_shaped_and_uses_canonical_site_url(self):
        response = self.client.get(reverse("security-txt"))
        content = response.content.decode("utf-8")
        fields = dict(line.split(": ", 1) for line in content.strip().splitlines())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/plain"))
        self.assertEqual(response["Cache-Control"], "public, max-age=86400")
        self.assertEqual(fields["Contact"], "mailto:security@example.test")
        self.assertEqual(fields["Preferred-Languages"], "zh, en, ja")
        self.assertEqual(
            fields["Canonical"],
            "https://blog.example.test/.well-known/security.txt",
        )
        expires = datetime.fromisoformat(fields["Expires"].replace("Z", "+00:00"))
        remaining_days = (expires - datetime.now(expires.tzinfo)).days
        self.assertGreaterEqual(remaining_days, 178)
        self.assertLessEqual(remaining_days, 180)

    def test_production_404_uses_devenir_template_without_debug_details(self):
        response = self.client.get("/definitely-not-a-real-route/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "signal absent", status_code=404)
        self.assertNotContains(response, "Traceback", status_code=404)
        self.assertContains(response, "noindex, nofollow", status_code=404)
        self.assertContains(response, "滇ICP备2025068499号-1", status_code=404)
        self.assertContains(response, "滇公网安备53010302001568号", status_code=404)

    def test_board_404_selects_board_specific_error_visual(self):
        response = self.client.get("/boards/skateboard/not-a-real-route/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(
            response,
            "images/errors/alpha-error-visual-skateboard.webp",
            status_code=404,
        )
        self.assertContains(response, "error-page--skateboard", status_code=404)

    @override_settings(ERROR_PREVIEW_ENABLED=False)
    def test_error_preview_is_hidden_in_production(self):
        response = self.client.get("/_errors/general/500/")

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("X-Error-Preview", response)

    def test_production_500_response_hides_exception_details(self):
        request = RequestFactory().get("/broken/")

        response = server_error(request)
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 500)
        self.assertIn("system unstable", content)
        self.assertNotIn("Traceback", content)


@override_settings(ERROR_PREVIEW_ENABLED=True)
class ErrorPreviewTest(TestCase):
    def test_error_preview_exposes_each_supported_variant(self):
        for variant in ("general", "skateboard", "music", "coding"):
            with self.subTest(variant=variant):
                response = self.client.get(f"/_errors/{variant}/403/")
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response["X-Error-Preview"], "1")
                self.assertContains(
                    response,
                    f"error-page--{variant}",
                    status_code=403,
                )

    def test_error_preview_rejects_unknown_variant_and_status(self):
        self.assertEqual(self.client.get("/_errors/unknown/404/").status_code, 404)
        self.assertEqual(self.client.get("/_errors/general/418/").status_code, 404)
