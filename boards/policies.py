"""ORM adapters for Board-scoped authorization decisions.

This module is the single entry point for Board, Post, and Comment business
authorization. It does not yet replace existing Admin, View, or API checks;
accounts_linear stage 4 and 5 will connect those runtime entry points.
"""

from typing import TYPE_CHECKING

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


def can_create_post(user, board: Board) -> bool:
    return _allows(user, board, BoardAction.CREATE_POST)


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
