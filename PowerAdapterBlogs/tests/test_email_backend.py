from pathlib import Path
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from PowerAdapterBlogs.email_backends import IPv4FailoverEmailBackend


@override_settings(
    EMAIL_HOST="smtp.gmail.com",
    EMAIL_PORT=465,
    EMAIL_HOST_USER="mailer@example.test",
    EMAIL_HOST_PASSWORD="test-password",
    EMAIL_USE_SSL=True,
    EMAIL_USE_TLS=False,
    EMAIL_TIMEOUT=2,
    EMAIL_SMTP_IPV4_FALLBACKS=("74.125.195.108",),
)
class IPv4FailoverEmailBackendTests(SimpleTestCase):
    @patch("PowerAdapterBlogs.email_backends.socket.getaddrinfo")
    def test_retries_configured_ipv4_when_dns_candidate_times_out(self, getaddrinfo):
        getaddrinfo.return_value = [
            (2, 1, 6, "", ("74.125.135.109", 465)),
        ]
        connection = Mock()
        backend = IPv4FailoverEmailBackend()
        backend._create_connection = Mock(
            side_effect=[TimeoutError("unreachable"), connection]
        )

        opened = backend.open()

        self.assertTrue(opened)
        self.assertIs(backend.connection, connection)
        self.assertEqual(
            [call.args[0] for call in backend._create_connection.call_args_list],
            ["74.125.135.109", "74.125.195.108"],
        )
        connection.login.assert_called_once_with(
            "mailer@example.test",
            "test-password",
        )

    @patch("PowerAdapterBlogs.email_backends.socket.getaddrinfo")
    def test_ignores_ipv6_dns_results(self, getaddrinfo):
        getaddrinfo.return_value = [
            (10, 1, 6, "", ("2404:6800:4008:c06::6d", 465, 0, 0)),
            (2, 1, 6, "", ("74.125.135.109", 465)),
        ]
        backend = IPv4FailoverEmailBackend()

        self.assertEqual(
            backend._candidate_ipv4s(),
            ("74.125.135.109", "74.125.195.108"),
        )

    @override_settings(EMAIL_SMTP_IPV4_FALLBACKS=("2001:db8::1",))
    def test_rejects_ipv6_fallback_configuration(self):
        backend = IPv4FailoverEmailBackend()

        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "EMAIL_SMTP_IPV4_FALLBACKS only accepts IPv4 addresses",
        ):
            backend._configured_fallbacks()


class ProductionEmailEnvironmentContractTests(SimpleTestCase):
    def test_compose_passes_ipv4_failover_settings_to_application(self):
        project_root = Path(__file__).resolve().parents[2]
        compose = (project_root / "compose.production.yml").read_text(encoding="utf-8")

        self.assertIn("EMAIL_TIMEOUT: ${EMAIL_TIMEOUT}", compose)
        self.assertIn(
            "EMAIL_SMTP_IPV4_FALLBACKS: ${EMAIL_SMTP_IPV4_FALLBACKS}",
            compose,
        )
