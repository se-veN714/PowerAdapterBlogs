from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import MyUser
from config.models import ContentReport
from config.services import review_content_report
from security.models import AuditOutbox


@override_settings(
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "sessions": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    },
    CONTENT_REPORT_RATE_LIMIT=2,
    CONTENT_REPORT_RATE_WINDOW=3600,
)
class ContentReportFlowTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_public_footer_exposes_report_entry(self):
        response = self.client.get(reverse("about"))

        self.assertContains(response, f'href="{reverse("report-create")}"')
        self.assertContains(response, "投诉举报")

    def test_public_user_can_submit_and_track_report(self):
        response = self.client.post(
            reverse("report-create"),
            {
                "category": ContentReport.Category.ILLEGAL_HARMFUL,
                "target_path": "/Blogs/post/example/#comment-3",
                "description": "该评论疑似包含需要站点审核处置的不良信息。",
                "contact_email": "reporter@example.com",
            },
            REMOTE_ADDR="203.0.113.10",
        )

        report = ContentReport.objects.get()
        self.assertRedirects(response, reverse("report-status", args=[report.reference]))
        self.assertEqual(report.status, ContentReport.Status.PENDING)
        self.assertNotEqual(report.source_ip_digest, "")
        audit = AuditOutbox.objects.get(event_type="content_report.created")
        self.assertEqual(audit.event["target"]["id"], str(report.reference))
        self.assertNotIn("description", audit.event["change"]["after"])

        status_response = self.client.get(
            reverse("report-status", args=[report.reference])
        )
        self.assertContains(status_response, str(report.reference))
        self.assertContains(status_response, "待受理")
        self.assertNotContains(status_response, "reporter@example.com")
        self.assertNotContains(status_response, report.description)
        self.assertEqual(status_response["Cache-Control"], "private, no-store")
        self.assertEqual(status_response["Referrer-Policy"], "no-referrer")

    def test_report_rejects_external_target_url(self):
        response = self.client.post(
            reverse("report-create"),
            {
                "category": ContentReport.Category.OTHER,
                "target_path": "https://attacker.example/phishing",
                "description": "这是一个用于覆盖外部链接校验的有效长度描述。",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "仅接受本站路径", status_code=400)
        self.assertFalse(ContentReport.objects.exists())

    def test_report_submission_is_rate_limited(self):
        payload = {
            "category": ContentReport.Category.SPAM,
            "target_path": "/Blogs/post/example/",
            "description": "这是一个用于覆盖投诉举报限流的有效长度描述。",
        }
        self.assertEqual(
            self.client.post(reverse("report-create"), payload).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(reverse("report-create"), payload).status_code,
            302,
        )

        response = self.client.post(reverse("report-create"), payload)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "3600")
        self.assertEqual(ContentReport.objects.count(), 2)

    def test_superuser_review_is_atomic_and_audited(self):
        reviewer = MyUser.objects.create_superuser(
            email="report-reviewer@example.com",
            username="report-reviewer",
            password="test-password",
        )
        report = ContentReport.objects.create(
            category=ContentReport.Category.OTHER,
            description="这是一条等待处理的投诉举报说明。",
            source_ip_digest="a" * 64,
        )

        reviewed = review_content_report(
            actor=reviewer,
            report_id=report.pk,
            status=ContentReport.Status.RESOLVED,
            internal_note="reviewed",
            public_response="已完成核查处理。",
        )

        self.assertEqual(reviewed.status, ContentReport.Status.RESOLVED)
        self.assertIsNotNone(reviewed.resolved_at)
        self.assertTrue(
            AuditOutbox.objects.filter(
                event_type="content_report.reviewed",
                event__target__id=str(report.reference),
            ).exists()
        )
