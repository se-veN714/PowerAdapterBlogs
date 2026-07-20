"""Transactional Post workflow services shared by HTTP and Admin entry points."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from Blogs.models import Post
from Blogs.revisions import create_revision
from boards.policies import can_publish_post, can_review_post, can_submit_post


@transaction.atomic
def submit_post_for_review(*, post: Post, user) -> Post:
    locked_post = Post.objects.select_for_update().get(pk=post.pk)
    if not can_submit_post(user, locked_post):
        raise PermissionDenied("You cannot submit this post for review.")
    if locked_post.status != Post.STATUS_DRAFT:
        raise ValidationError("Only draft posts can be submitted for review.")

    locked_post.status = Post.STATUS_REVIEW
    locked_post.save(update_fields=["status", "update_time"])
    return locked_post


@transaction.atomic
def approve_post(*, post: Post, user) -> Post:
    locked_post = Post.objects.select_for_update().get(pk=post.pk)
    if not can_publish_post(user, locked_post):
        raise PermissionDenied("You cannot publish this post.")
    if locked_post.status != Post.STATUS_REVIEW:
        raise ValidationError("Only posts under review can be published.")

    locked_post.status = Post.STATUS_NORMAL
    locked_post.save(update_fields=["status", "update_time"])
    create_revision(
        locked_post,
        user,
        change_type="minor",
        edit_summary="审核通过 → 已发布",
    )
    return locked_post


@transaction.atomic
def reject_post(*, post: Post, user) -> Post:
    locked_post = Post.objects.select_for_update().get(pk=post.pk)
    if not can_review_post(user, locked_post):
        raise PermissionDenied("You cannot reject this post.")
    if locked_post.status != Post.STATUS_REVIEW:
        raise ValidationError("Only posts under review can be rejected.")

    locked_post.status = Post.STATUS_DRAFT
    locked_post.save(update_fields=["status", "update_time"])
    return locked_post


@transaction.atomic
def unpublish_post(*, post: Post, user) -> Post:
    locked_post = Post.objects.select_for_update().get(pk=post.pk)
    if not can_publish_post(user, locked_post):
        raise PermissionDenied("You cannot unpublish this post.")
    if locked_post.status != Post.STATUS_NORMAL:
        raise ValidationError("Only published posts can be unpublished.")

    locked_post.status = Post.STATUS_DELETE
    locked_post.save(update_fields=["status", "update_time"])
    return locked_post
