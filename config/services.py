from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from security.outbox import enqueue_audit_event

from .models import ContentReport


@transaction.atomic
def submit_content_report(*, reporter, client_ip_digest, **report_fields):
    report = ContentReport.objects.create(
        submitted_by=reporter,
        source_ip_digest=client_ip_digest,
        **report_fields,
    )
    enqueue_audit_event(
        event_type="content_report.created",
        actor={
            "type": "user" if reporter is not None else "anonymous",
            "id": str(reporter.pk) if reporter is not None else None,
        },
        target={"type": "content_report", "id": str(report.reference)},
        context={"source": "public-web"},
        change={
            "before": {},
            "after": {"category": report.category, "status": report.status},
        },
        outcome={"status": "success", "error_code": None},
    )
    return report


@transaction.atomic
def review_content_report(
    *, actor, report_id, status, internal_note, public_response
):
    if not actor.is_active or not actor.is_superuser:
        raise PermissionDenied("仅超级管理员可处理投诉举报。")
    report = ContentReport.objects.select_for_update().get(pk=report_id)
    before_status = report.status
    report.status = status
    report.internal_note = internal_note
    report.public_response = public_response
    if status in {ContentReport.Status.RESOLVED, ContentReport.Status.REJECTED}:
        report.resolved_at = report.resolved_at or timezone.now()
    else:
        report.resolved_at = None
    report.save(
        update_fields=(
            "status",
            "internal_note",
            "public_response",
            "resolved_at",
            "updated_at",
        )
    )
    enqueue_audit_event(
        event_type="content_report.reviewed",
        actor={"type": "user", "id": str(actor.pk)},
        target={"type": "content_report", "id": str(report.reference)},
        context={"source": "django-admin"},
        change={
            "before": {"status": before_status},
            "after": {"status": report.status},
        },
        outcome={"status": "success", "error_code": None},
    )
    return report
