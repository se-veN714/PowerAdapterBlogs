from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class VerificationEmailTemplateTests(SimpleTestCase):
    templates = {
        "emails/accounts/password_change_code.html": "确认密码修改",
        "emails/accounts/board_access_code.html": "确认板块权限申请",
        "emails/accounts/mfa_enrollment_code.html": "确认动态验证码绑定",
    }

    def test_verification_emails_share_devenir_layout(self):
        context = {
            "user": SimpleNamespace(username="PowerAdapter"),
            "code": "841726",
            "ttl_minutes": 10,
        }

        for template_name, heading in self.templates.items():
            with self.subTest(template_name=template_name):
                html = render_to_string(template_name, context)
                self.assertIn("<!doctype html>", html)
                self.assertIn("POWERADAPTER", html)
                self.assertIn(heading, html)
                self.assertIn("841726", html)
                self.assertIn("font-size: 36px", html)
                self.assertIn("poweradapter.xyz", html)
                self.assertNotIn("font-size: 72px", html)
