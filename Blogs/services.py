"""Transactional Post workflow services shared by HTTP and Admin entry points."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from Blogs.models import Post, PostRevision, PostWorkflowEvent
from Blogs.revisions import create_revision
from boards.policies import can_publish_post, can_review_post, can_submit_post


class RevisionConflict(ValidationError):
    """The editor submitted a form based on an obsolete revision head."""

    default_code = "revision_conflict"


def workflow_event_type_for_transition(
    from_status: int,
    to_status: int,
) -> str:
    """Map a Post status transition to its domain event type."""
    transitions = {
        (Post.STATUS_DRAFT, Post.STATUS_REVIEW): PostWorkflowEvent.EventType.SUBMITTED,
        (Post.STATUS_REVIEW, Post.STATUS_NORMAL): PostWorkflowEvent.EventType.APPROVED,
        (Post.STATUS_REVIEW, Post.STATUS_DRAFT): PostWorkflowEvent.EventType.REJECTED,
        (Post.STATUS_NORMAL, Post.STATUS_DELETE): PostWorkflowEvent.EventType.UNPUBLISHED,
    }
    if (from_status, to_status) in transitions:
        return transitions[(from_status, to_status)]
    if to_status == Post.STATUS_DRAFT:
        return PostWorkflowEvent.EventType.RETURNED_TO_DRAFT
    return PostWorkflowEvent.EventType.STATUS_CHANGED


def record_post_workflow_event(
    *,
    post: Post,
    actor,
    from_status: int,
    to_status: int,
    revision: PostRevision | None,
    note: str = "",
) -> PostWorkflowEvent:
    """Record one status transition inside the caller's transaction."""
    if from_status == to_status:
        raise ValidationError("Workflow events require an actual status transition.")
    return PostWorkflowEvent.objects.create(
        post=post,
        actor=actor,
        event_type=workflow_event_type_for_transition(from_status, to_status),
        from_status=from_status,
        to_status=to_status,
        revision=revision,
        note=note,
    )


def _latest_revision(post: Post) -> PostRevision | None:
    return post.revisions.order_by("-major", "-minor").first()


@transaction.atomic
def commit_post_form(
    *,
    form,
    editor,
    change_type: str,
    edit_summary: str,
    expected_revision_id: int | None,
) -> Post:
    """Persist a validated PostForm and its revision as one commit.

    The hidden ``expected_revision_id`` is an optimistic concurrency token. The
    row lock then serializes the short database commit itself.
    """
    is_new = form.instance.pk is None
    previous_status = None
    if not is_new:
        locked_post = Post.objects.select_for_update().get(pk=form.instance.pk)
        previous_status = locked_post.status
        current_revision_id = (
            locked_post.revisions.order_by("-major", "-minor")
            .values_list("pk", flat=True)
            .first()
        )
        if current_revision_id != expected_revision_id:
            raise RevisionConflict(
                "文章在你打开编辑页后已产生新版本。当前提交未保存，请刷新页面后合并修改。"
            )

    post = form.save()
    revision = create_revision(
        post,
        editor,
        change_type=change_type,
        edit_summary=edit_summary,
    )
    if previous_status is not None and previous_status != post.status:
        record_post_workflow_event(
            post=post,
            actor=editor,
            from_status=previous_status,
            to_status=post.status,
            revision=revision,
            note="内容编辑触发状态回退",
        )
    return post


@transaction.atomic
def submit_post_for_review(*, post: Post, user) -> Post:
    locked_post = Post.objects.select_for_update().get(pk=post.pk)
    if not can_submit_post(user, locked_post):
        raise PermissionDenied("You cannot submit this post for review.")
    if locked_post.status != Post.STATUS_DRAFT:
        raise ValidationError("Only draft posts can be submitted for review.")

    from_status = locked_post.status
    locked_post.status = Post.STATUS_REVIEW
    locked_post.save(update_fields=["status", "update_time"])
    record_post_workflow_event(
        post=locked_post,
        actor=user,
        from_status=from_status,
        to_status=locked_post.status,
        revision=_latest_revision(locked_post),
    )
    return locked_post


@transaction.atomic
def approve_post(*, post: Post, user) -> Post:
    locked_post = Post.objects.select_for_update().get(pk=post.pk)
    if not can_publish_post(user, locked_post):
        raise PermissionDenied("You cannot publish this post.")
    if locked_post.status != Post.STATUS_REVIEW:
        raise ValidationError("Only posts under review can be published.")

    from_status = locked_post.status
    locked_post.status = Post.STATUS_NORMAL
    locked_post.save(update_fields=["status", "update_time"])
    record_post_workflow_event(
        post=locked_post,
        actor=user,
        from_status=from_status,
        to_status=locked_post.status,
        revision=_latest_revision(locked_post),
    )
    return locked_post


@transaction.atomic
def reject_post(*, post: Post, user) -> Post:
    locked_post = Post.objects.select_for_update().get(pk=post.pk)
    if not can_review_post(user, locked_post):
        raise PermissionDenied("You cannot reject this post.")
    if locked_post.status != Post.STATUS_REVIEW:
        raise ValidationError("Only posts under review can be rejected.")

    from_status = locked_post.status
    locked_post.status = Post.STATUS_DRAFT
    locked_post.save(update_fields=["status", "update_time"])
    record_post_workflow_event(
        post=locked_post,
        actor=user,
        from_status=from_status,
        to_status=locked_post.status,
        revision=_latest_revision(locked_post),
    )
    return locked_post


@transaction.atomic
def unpublish_post(*, post: Post, user) -> Post:
    locked_post = Post.objects.select_for_update().get(pk=post.pk)
    if not can_publish_post(user, locked_post):
        raise PermissionDenied("You cannot unpublish this post.")
    if locked_post.status != Post.STATUS_NORMAL:
        raise ValidationError("Only published posts can be unpublished.")

    from_status = locked_post.status
    locked_post.status = Post.STATUS_DELETE
    locked_post.save(update_fields=["status", "update_time"])
    record_post_workflow_event(
        post=locked_post,
        actor=user,
        from_status=from_status,
        to_status=locked_post.status,
        revision=_latest_revision(locked_post),
    )
    return locked_post
