"""ORM adapters for Board-scoped authorization decisions.

This module is the single entry point for Board, Post, and Comment business
authorization. It does not yet replace existing Admin, View, or API checks;
accounts_linear stage 4 and 5 will connect those runtime entry points.
"""

from typing import TYPE_CHECKING

from django.db.models import Count, Q

from boards.access_rules import BoardAction, allows_board_action
from boards.models import Board, BoardMembership

if TYPE_CHECKING:
    from Blogs.models import Post
    from comment.models import Comment


def _is_active_authenticated(user) -> bool:
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
    )


def _is_active_superuser(user) -> bool:
    return _is_active_authenticated(user) and bool(
        getattr(user, "is_superuser", False)
    )


def board_for_post(post: "Post") -> Board | None:
    """Resolve exactly one Board from a Post's Category, otherwise fail closed."""
    category_id = getattr(post, "category_id", None)
    if category_id is None:
        return None

    matches = list(Board.objects.filter(category_id=category_id).order_by("pk")[:2])
    if len(matches) != 1:
        return None
    return matches[0]


def board_for_comment(comment: "Comment") -> Board | None:
    """Resolve a Comment's Board through its Post."""
    post = getattr(comment, "post", None)
    if post is None:
        return None
    return board_for_post(post)


def get_active_membership(user, board: Board | None) -> BoardMembership | None:
    """Return the active membership for one active user and active Board."""
    if (
        not _is_active_authenticated(user)
        or board is None
        or board.pk is None
        or not board.is_active
    ):
        return None

    return (
        BoardMembership.objects.filter(
            board=board,
            user=user,
            is_active=True,
        )
        .select_related("board", "user")
        .first()
    )


def _unambiguous_category_ids():
    """Category ids mapped to exactly one Board, matching ``board_for_post``."""
    return (
        Board.objects.exclude(category_id=None)
        .values("category_id")
        .annotate(board_count=Count("pk"))
        .filter(board_count=1)
        .values("category_id")
    )


def _membership_category_ids(user, roles):
    if not _is_active_authenticated(user):
        return BoardMembership.objects.none().values("board__category_id")

    return BoardMembership.objects.filter(
        user=user,
        is_active=True,
        role__in=roles,
        board__is_active=True,
        board__category_id__isnull=False,
        board__category_id__in=_unambiguous_category_ids(),
    ).values("board__category_id")


def _has_scoped_role(user, roles) -> bool:
    if _is_active_superuser(user):
        return True
    return _membership_category_ids(user, roles).exists()


def _allows(
    user,
    board: Board | None,
    action: BoardAction,
    *,
    owns_object: bool = False,
) -> bool:
    if not _is_active_authenticated(user):
        return False
    if _is_active_superuser(user):
        return True

    membership = get_active_membership(user, board)
    if membership is None:
        return False

    return allows_board_action(
        role=membership.role,
        action=action,
        membership_is_active=membership.is_active,
        same_board=membership.board_id == board.pk,
        owns_object=owns_object,
    )


def can_create_board(user) -> bool:
    """Only superusers may create a code-backed Board."""
    return _is_active_superuser(user)


def can_delete_board(user, board: Board | None = None) -> bool:
    """Only superusers may delete a code-backed Board."""
    return _is_active_superuser(user)


def can_change_board_structure(user, board: Board | None = None) -> bool:
    """Only superusers may change slug or frontend code bindings."""
    return _is_active_superuser(user)


def can_change_board_settings(user, board: Board) -> bool:
    """Allow operational Board settings without granting structural changes."""
    return _allows(user, board, BoardAction.CHANGE_BOARD_SETTINGS)


def can_manage_board_members(user, board: Board) -> bool:
    return _allows(user, board, BoardAction.MANAGE_BOARD_MEMBERS)


def can_manage_board_content(user, board: Board) -> bool:
    """Manage code-backed Board Index content without changing Board structure."""
    return _allows(user, board, BoardAction.CHANGE_BOARD_SETTINGS)


def can_access_board_admin(user) -> bool:
    if _is_active_superuser(user):
        return True
    if not _is_active_authenticated(user):
        return False
    return BoardMembership.objects.filter(
        user=user,
        role=BoardMembership.Role.MANAGER,
        is_active=True,
        board__is_active=True,
    ).exists()


def boards_manageable_by(user, queryset):
    if _is_active_superuser(user):
        return queryset
    if not _is_active_authenticated(user):
        return queryset.none()
    return queryset.filter(
        is_active=True,
        memberships__user=user,
        memberships__role=BoardMembership.Role.MANAGER,
        memberships__is_active=True,
    ).distinct()


def can_create_post(user, board: Board) -> bool:
    return _allows(user, board, BoardAction.CREATE_POST)


def can_access_post_admin(user) -> bool:
    return _has_scoped_role(
        user,
        (
            BoardMembership.Role.CONTRIBUTOR,
            BoardMembership.Role.EDITOR,
            BoardMembership.Role.REVIEWER,
            BoardMembership.Role.MANAGER,
        ),
    )


def can_change_posts_in_admin(user) -> bool:
    return _has_scoped_role(
        user,
        (
            BoardMembership.Role.CONTRIBUTOR,
            BoardMembership.Role.EDITOR,
            BoardMembership.Role.MANAGER,
        ),
    )


def can_create_post_in_any_board(user) -> bool:
    return can_change_posts_in_admin(user)


def can_review_posts_in_admin(user) -> bool:
    return _has_scoped_role(
        user,
        (BoardMembership.Role.REVIEWER, BoardMembership.Role.MANAGER),
    )


def categories_available_to(user, queryset):
    """Categories belonging to any unambiguous active Membership."""
    if _is_active_superuser(user):
        return queryset
    category_ids = _membership_category_ids(
        user,
        (
            BoardMembership.Role.CONTRIBUTOR,
            BoardMembership.Role.EDITOR,
            BoardMembership.Role.REVIEWER,
            BoardMembership.Role.MANAGER,
        ),
    )
    return queryset.filter(pk__in=category_ids).distinct()


def categories_for_post_creation(user, queryset):
    if _is_active_superuser(user):
        return queryset
    category_ids = _membership_category_ids(
        user,
        (
            BoardMembership.Role.CONTRIBUTOR,
            BoardMembership.Role.EDITOR,
            BoardMembership.Role.MANAGER,
        ),
    )
    return queryset.filter(pk__in=category_ids).distinct()


def posts_visible_to(user, queryset):
    if _is_active_superuser(user):
        return queryset
    if not _is_active_authenticated(user):
        return queryset.none()

    all_post_categories = _membership_category_ids(
        user,
        (BoardMembership.Role.REVIEWER, BoardMembership.Role.MANAGER),
    )
    own_post_categories = _membership_category_ids(
        user,
        (BoardMembership.Role.CONTRIBUTOR, BoardMembership.Role.EDITOR),
    )
    return queryset.filter(
        Q(category_id__in=all_post_categories)
        | Q(category_id__in=own_post_categories, owner=user)
    ).distinct()


def posts_editable_by(user, queryset):
    if _is_active_superuser(user):
        return queryset
    if not _is_active_authenticated(user):
        return queryset.none()

    manager_categories = _membership_category_ids(
        user,
        (BoardMembership.Role.MANAGER,),
    )
    editor_categories = _membership_category_ids(
        user,
        (BoardMembership.Role.EDITOR,),
    )
    contributor_categories = _membership_category_ids(
        user,
        (BoardMembership.Role.CONTRIBUTOR,),
    )
    return queryset.filter(
        Q(category_id__in=manager_categories)
        | Q(category_id__in=editor_categories, owner=user)
        | Q(
            category_id__in=contributor_categories,
            owner=user,
            status=queryset.model.STATUS_DRAFT,
        )
    ).distinct()


def posts_publishable_by(user, queryset):
    """Return posts the user may publish or unpublish without per-row queries."""
    if _is_active_superuser(user):
        return queryset
    if not _is_active_authenticated(user):
        return queryset.none()

    category_ids = _membership_category_ids(
        user,
        (BoardMembership.Role.REVIEWER, BoardMembership.Role.MANAGER),
    )
    return queryset.filter(category_id__in=category_ids).exclude(owner=user).distinct()


def published_posts_visible_to(user, queryset):
    """Return published public posts plus permitted Board-scoped internal posts."""
    published = queryset.filter(status=queryset.model.STATUS_NORMAL)
    if _is_active_superuser(user):
        return published

    public_posts = Q(visibility=queryset.model.VISIBILITY_PUBLIC)
    if not _is_active_authenticated(user):
        return published.filter(public_posts)

    scoped_internal_ids = posts_visible_to(
        user,
        published.filter(visibility=queryset.model.VISIBILITY_STAFF_ONLY),
    ).values("pk")
    return published.filter(public_posts | Q(pk__in=scoped_internal_ids)).distinct()


def can_view_post(user, post: "Post") -> bool:
    if _is_active_superuser(user):
        return True
    membership = get_active_membership(user, board_for_post(post))
    if membership is None:
        return False
    if membership.role in {
        BoardMembership.Role.REVIEWER,
        BoardMembership.Role.MANAGER,
    }:
        return True
    return (
        membership.role
        in {BoardMembership.Role.CONTRIBUTOR, BoardMembership.Role.EDITOR}
        and getattr(post, "owner_id", None) == getattr(user, "pk", None)
    )


def can_view_published_post(user, post: "Post") -> bool:
    if post.status != post.STATUS_NORMAL:
        return False
    if post.visibility == post.VISIBILITY_PUBLIC:
        return True
    return can_view_post(user, post)


def can_view_post_detail(user, post: "Post") -> bool:
    """Published visibility plus an author-only preview for pre-publication."""
    if post.status == post.STATUS_NORMAL:
        return can_view_published_post(user, post)
    if post.status not in {post.STATUS_DRAFT, post.STATUS_REVIEW}:
        return False
    return (
        _is_active_authenticated(user)
        and getattr(post, "owner_id", None) == getattr(user, "pk", None)
    )


def can_edit_post(user, post: "Post") -> bool:
    board = board_for_post(post)
    owns_post = getattr(post, "owner_id", None) == getattr(user, "pk", None)

    if not owns_post:
        action = BoardAction.EDIT_ANY_POST
    elif post.status == post.STATUS_DRAFT:
        action = BoardAction.EDIT_OWN_DRAFT
    else:
        action = BoardAction.EDIT_OWN_POST

    return _allows(user, board, action, owns_object=owns_post)


def can_submit_post(user, post: "Post") -> bool:
    owns_post = getattr(post, "owner_id", None) == getattr(user, "pk", None)
    return _allows(
        user,
        board_for_post(post),
        BoardAction.SUBMIT_POST,
        owns_object=owns_post,
    )


def can_view_review_queue(user, board: Board) -> bool:
    return _allows(user, board, BoardAction.VIEW_REVIEW_QUEUE)


def can_review_post(user, post: "Post") -> bool:
    owns_post = getattr(post, "owner_id", None) == getattr(user, "pk", None)
    return _allows(
        user,
        board_for_post(post),
        BoardAction.REVIEW_POST,
        owns_object=owns_post,
    )


def can_publish_post(user, post: "Post") -> bool:
    owns_post = getattr(post, "owner_id", None) == getattr(user, "pk", None)
    return _allows(
        user,
        board_for_post(post),
        BoardAction.PUBLISH_POST,
        owns_object=owns_post,
    )


def can_moderate_comment(user, comment: "Comment") -> bool:
    return _allows(
        user,
        board_for_comment(comment),
        BoardAction.MODERATE_COMMENT,
    )


def can_access_comment_admin(user) -> bool:
    return _has_scoped_role(
        user,
        (BoardMembership.Role.REVIEWER, BoardMembership.Role.MANAGER),
    )


def comments_visible_to_moderator(user, queryset):
    if _is_active_superuser(user):
        return queryset
    if not _is_active_authenticated(user):
        return queryset.none()
    category_ids = _membership_category_ids(
        user,
        (BoardMembership.Role.REVIEWER, BoardMembership.Role.MANAGER),
    )
    return queryset.filter(post__category_id__in=category_ids).distinct()


def can_view_post_revision(user, revision) -> bool:
    return can_view_post(user, revision.post)


def post_revisions_visible_to(user, queryset):
    if _is_active_superuser(user):
        return queryset
    if not _is_active_authenticated(user):
        return queryset.none()

    all_post_categories = _membership_category_ids(
        user,
        (BoardMembership.Role.REVIEWER, BoardMembership.Role.MANAGER),
    )
    own_post_categories = _membership_category_ids(
        user,
        (BoardMembership.Role.CONTRIBUTOR, BoardMembership.Role.EDITOR),
    )
    return queryset.filter(
        Q(post__category_id__in=all_post_categories)
        | Q(post__category_id__in=own_post_categories, post__owner=user)
    ).distinct()
