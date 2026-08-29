from django.test import SimpleTestCase

from PowerAdapterBlogs.settings import base


class SecurityLogRetentionConfigurationTest(SimpleTestCase):
    def test_file_logs_are_rotated_daily_for_at_least_six_months(self):
        for name in ("info_file", "warning_file", "error_file"):
            handler = base.LOGGING["handlers"][name]
            self.assertEqual(
                handler["class"], "logging.handlers.TimedRotatingFileHandler"
            )
            self.assertEqual(handler["when"], "midnight")
            self.assertGreaterEqual(handler["backupCount"], 183)

    def test_all_application_loggers_reach_persistent_files(self):
        root_handlers = set(base.LOGGING["root"]["handlers"])
        self.assertTrue(
            {"info_file", "warning_file", "error_file"}.issubset(root_handlers)
        )
        request_handlers = set(base.LOGGING["loggers"]["django.request"]["handlers"])
        self.assertTrue({"warning_file", "error_file"}.issubset(request_handlers))
