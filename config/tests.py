from datetime import datetime

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from config.views import server_error


class SiteInformationPageTest(TestCase):
    def test_about_page_is_public_and_explains_board_boundary(self):
        response = self.client.get(reverse("about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "每个板块都是独立表达")
        self.assertContains(response, "BoardMembership")

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

    def test_production_500_response_hides_exception_details(self):
        request = RequestFactory().get("/broken/")

        response = server_error(request)
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 500)
        self.assertIn("system unstable", content)
        self.assertNotIn("Traceback", content)
