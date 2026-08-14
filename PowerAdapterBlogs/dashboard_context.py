"""Read-only context assembly for the first-party Devenir dashboard."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.admin.models import LogEntry
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from Blogs.models import Post, PostImage, PostVisit, PostWorkflowEvent
from accounts.models import MfaTotpDevice
from boards.membership_step_up import MANAGE_MEMBERSHIP_PERMISSION
from boards.models import BoardMembershipEvent
from boards.policies import (
    can_access_comment_admin,
    can_create_post_in_any_board,
    comments_visible_to_moderator,
    posts_editable_by,
    posts_visible_to,
)
from comment.models import Comment
from operations.policies import can_view_security_operations
from security.models import SecureLogEntry


def _url(name: str, fallback: str | None = None) -> str | None:
    try:
        return reverse(name)
    except NoReverseMatch:
        return fallback


def dashboard_navigation(request) -> list[dict]:
    user = request.user
    return [
        {"key": "overview", "label": "Overview", "url": _url("dashboard:overview")},
        {
            "key": "memberships",
            "label": "Memberships",
            "url": _url("board-dashboard:memberships"),
            "visible": user.has_perm(MANAGE_MEMBERSHIP_PERMISSION),
        },
        {
            "key": "audit",
            "label": "Audit Events",
            "url": _url("dashboard:audit"),
        },
        {"key": "posts", "label": "Posts", "url": _url("dashboard:posts")},
        {
            "key": "comments",
            "label": "Comments",
            "url": _url("dashboard:comments"),
            "visible": can_access_comment_admin(user),
        },
        {"key": "media", "label": "Media", "url": _url("dashboard:media")},
        {
            "key": "settings",
            "label": "Site Settings",
            "url": _url("dashboard:settings"),
        },
    ]


def dashboard_shell_context(request, *, active: str, title: str) -> dict:
    user = request.user
    device = MfaTotpDevice.objects.filter(
        user=user,
        status=MfaTotpDevice.Status.ACTIVE,
    ).only("status").first()
    return {
        "dashboard_active": active,
        "dashboard_page_title": title,
        "dashboard_navigation": [
            item for item in dashboard_navigation(request) if item.get("visible", True)
        ],
        "dashboard_utility_navigation": [
            {"label": "Public Home", "url": _url("index")},
            {"label": "My Profile", "url": _url("accounts:my-profile")},
            {"label": "MFA Security", "url": _url("accounts:mfa-settings")},
            {"label": "Legacy Admin", "url": _url("cus_admin:index")},
            *(
                [{"label": "Security Ops", "url": _url("operations:security")}]
                if can_view_security_operations(user)
                else []
            ),
        ],
        "dashboard_identity": {
            "username": user.username,
            "environment_label": "ROOT" if user.is_superuser else "OPERATOR",
            "mfa_state_label": "VERIFIED" if device else "NOT ENROLLED",
            # Authorization was already enforced by the dashboard middleware/view.
            # Do not re-run the mutating session validator while building UI context.
            "session_verified": bool(device),
        },
    }


def _hourly_visits(start, visible_posts) -> list[int]:
    buckets = [0] * 8
    for created_at in PostVisit.objects.filter(
        created_time__gte=start,
        post__in=visible_posts,
    ).values_list("created_time", flat=True):
        local_hour = timezone.localtime(created_at).hour
        buckets[min(local_hour // 3, 7)] += 1
    return buckets


def overview_context(request) -> dict:
    now = timezone.now()
    shell = dashboard_shell_context(request, active="overview", title="控制台总览")
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    visible_posts = posts_visible_to(request.user, Post.objects.all())
    post_counts = {
        row["status"]: row["count"]
        for row in visible_posts.values("status").annotate(count=models.Count("pk"))
    }
    month_posts = visible_posts.filter(update_time__gte=month).exclude(
        status=Post.STATUS_DELETE
    )
    month_total = month_posts.count()
    month_published = month_posts.filter(status=Post.STATUS_NORMAL).count()
    moderation_visible = can_access_comment_admin(request.user)
    visible_comments = comments_visible_to_moderator(
        request.user,
        Comment.objects.all(),
    )
    pending_comments = visible_comments.filter(status=Comment.Status.PENDING)
    oldest_pending = pending_comments.order_by("created_time").first()
    wait_label = None
    if oldest_pending:
        delta = max(now - oldest_pending.created_time, timedelta())
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60
        wait_label = f"{hours}h {minutes:02d}m"
    security_visible = can_view_security_operations(request.user)
    rejected_actions = LogEntry.objects.filter(
        action_time__gte=today,
        change_message__icontains="拒绝",
    ).count()
    media_count = PostImage.objects.filter(post__in=visible_posts).count()
    media_count += visible_posts.exclude(cover="").exclude(cover__isnull=True).count()
    can_create_post = can_create_post_in_any_board(request.user)
    return {
        **shell,
        "content_pulse": {
            "published_count": post_counts.get(Post.STATUS_NORMAL, 0),
            "draft_count": post_counts.get(Post.STATUS_DRAFT, 0),
            "review_count": post_counts.get(Post.STATUS_REVIEW, 0),
            "scheduled_count": None,
            "monthly_completion": (
                round(month_published / month_total * 100) if month_total else None
            ),
            "posts_url": _url("dashboard:posts"),
        },
        "moderation_summary": {
            "visible": moderation_visible,
            "pending_comment_count": pending_comments.count() if moderation_visible else None,
            "high_risk_count": None,
            "longest_wait_label": wait_label if moderation_visible else None,
            "moderation_url": _url("dashboard:comments"),
        },
        "audience_today": {
            "page_views": PostVisit.objects.filter(
                created_time__gte=today,
                visit_type=PostVisit.PV_VISIT,
                post__in=visible_posts,
            ).count(),
            "unique_visitors": PostVisit.objects.filter(
                created_time__gte=today,
                visit_type=PostVisit.UV_VISIT,
                post__in=visible_posts,
            ).values("uid").distinct().count(),
            "hourly_points": _hourly_visits(today, visible_posts),
            "analytics_url": None,
        },
        "asset_summary": {
            "total_count": media_count,
            "storage_label": None,
            "unused_count": None,
            "optimization_count": None,
            "media_url": _url("dashboard:media"),
        },
        "security_summary": {
            "visible": security_visible,
            "mfa_label": shell["dashboard_identity"]["mfa_state_label"],
            "audit_event_count": (
                SecureLogEntry.objects.filter(computed_at__gte=today).count()
                if security_visible
                else None
            ),
            "rejected_action_count": rejected_actions if security_visible else None,
            "external_uptime_label": None,
            "security_url": (
                _url("operations:security") if security_visible else None
            ),
        },
        "quick_actions": [
            {
                "key": "N",
                "label": "新建文章",
                "url": _url("Blogs:post_create"),
                "enabled": can_create_post,
                "disabled_reason": "当前账号没有可投稿板块",
            },
            {
                "key": "U",
                "label": "文章媒体",
                "url": _url("dashboard:media"),
                "enabled": True,
            },
            {
                "key": "R",
                "label": "审核评论",
                "url": _url("dashboard:comments"),
                "enabled": moderation_visible,
                "disabled_reason": "当前账号没有评论审核权限",
            },
            {
                "key": "A",
                "label": "兼容管理区",
                "url": _url("cus_admin:index"),
                "enabled": True,
            },
        ],
    }


def posts_context(request) -> dict:
    base_queryset = posts_visible_to(
        request.user,
        Post.objects.select_related("category", "owner"),
    )
    queryset = base_queryset.order_by(
        "-update_time",
        "-pk",
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(desc__icontains=query)
            | Q(category__name__icontains=query)
        )
    if status.isdigit() and int(status) in dict(Post.STATUS_ITEMS):
        queryset = queryset.filter(status=int(status))
    page = Paginator(queryset, 12).get_page(request.GET.get("page"))
    editable_ids = set(
        posts_editable_by(request.user, base_queryset)
        .filter(pk__in=[post.pk for post in page.object_list])
        .values_list("pk", flat=True)
    )
    for post in page.object_list:
        post.dashboard_can_edit = post.pk in editable_ids
    counts = {
        row["status"]: row["count"]
        for row in base_queryset.values("status").annotate(count=models.Count("pk"))
    }
    return {
        **dashboard_shell_context(request, active="posts", title="文章工作台"),
        "posts": page,
        "page_obj": page,
        "selected_q": query,
        "selected_status": status,
        "status_choices": Post.STATUS_ITEMS,
        "post_counts": counts,
        "published_count": counts.get(Post.STATUS_NORMAL, 0),
        "draft_count": counts.get(Post.STATUS_DRAFT, 0),
        "review_count": counts.get(Post.STATUS_REVIEW, 0),
        "post_add_url": _url("Blogs:post_create"),
        "can_create_post": can_create_post_in_any_board(request.user),
    }


def comments_context(request) -> dict:
    visible = can_access_comment_admin(request.user)
    if not visible:
        raise PermissionDenied("当前账号没有评论审核权限。")
    base_queryset = comments_visible_to_moderator(
        request.user,
        Comment.objects.select_related("post", "user"),
    )
    queryset = base_queryset.order_by("created_time", "pk")
    status = request.GET.get("status", str(Comment.Status.PENDING.value))
    if status.isdigit() and int(status) in {int(choice.value) for choice in Comment.Status}:
        queryset = queryset.filter(status=int(status))
    selected = queryset.filter(pk=request.GET.get("selected")).first()
    if selected is None:
        selected = queryset.first()
    return {
        **dashboard_shell_context(request, active="comments", title="评论与审核"),
        "comments": queryset[:30],
        "selected_comment": selected,
        "selected_status": status,
        "comment_counts": {
            item.value: base_queryset.filter(status=item.value).count()
            for item in Comment.Status
        },
        "moderation_url": _url("moderation:comments"),
    }


def audit_context(request) -> dict:
    can_membership = request.user.has_perm(MANAGE_MEMBERSHIP_PERMISSION)
    can_security = can_view_security_operations(request.user)
    events = []
    if can_membership:
        events.extend(
            {
                "occurred_at": event.created_at,
                "kind": event.event_type.upper(),
                "target": f"{event.board_slug_snapshot} / {event.username_snapshot}",
                "actor": event.actor_username_snapshot or "SYSTEM",
                "source": event.source.upper(),
            }
            for event in BoardMembershipEvent.objects.all()[:30]
        )
    visible_posts = posts_visible_to(request.user, Post.objects.all())
    events.extend(
        {
            "occurred_at": event.created_at,
            "kind": event.event_type.upper(),
            "target": event.post.title,
            "actor": event.actor.username if event.actor else "SYSTEM",
            "source": "POST WORKFLOW",
        }
        for event in PostWorkflowEvent.objects.filter(post__in=visible_posts)
        .select_related("post", "actor")[:30]
    )
    events.sort(key=lambda item: item["occurred_at"], reverse=True)
    return {
        **dashboard_shell_context(request, active="audit", title="审计事件流"),
        "audit_events": events[:40],
        "can_view_security_audit": can_security,
        "security_url": _url("operations:security") if can_security else None,
    }


def media_context(request) -> dict:
    visible_posts = posts_visible_to(request.user, Post.objects.all())
    assets = []
    images = PostImage.objects.filter(post__in=visible_posts)
    covers = visible_posts.exclude(cover="").exclude(cover__isnull=True)
    for image in images.select_related("post").order_by("-pk")[:30]:
        assets.append(
            {
                "name": image.post_image.name.rsplit("/", 1)[-1],
                "url": image.post_image.url,
                "kind": "POST IMAGE",
                "usage": image.post.title,
                "alt": image.alt_text,
            }
        )
    for post in covers.select_related("category").order_by("-update_time")[:30]:
        assets.append(
            {
                "name": post.cover.name.rsplit("/", 1)[-1],
                "url": post.cover.url,
                "kind": "POST COVER",
                "usage": post.title,
                "alt": post.title,
            }
        )
    return {
        **dashboard_shell_context(request, active="media", title="媒体资源库"),
        "assets": assets[:30],
        "asset_count": images.count() + covers.count(),
        "upload_url": _url("Blogs:post_create"),
        "can_upload": can_create_post_in_any_board(request.user),
    }


def settings_context(request) -> dict:
    from django.conf import settings

    return {
        **dashboard_shell_context(request, active="settings", title="站点设置"),
        "site_configuration": {
            "site_title": "PowerAdapter",
            "language": settings.LANGUAGE_CODE,
            "time_zone": settings.TIME_ZONE,
            "theme": getattr(settings, "THEMES", "devenir"),
            "public_base_url": getattr(settings, "PUBLIC_BASE_URL", None),
        },
        "configuration_read_only": True,
    }
