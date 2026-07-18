"""Board-scoped authorization rules without database or HTTP dependencies."""

from enum import Enum
from types import MappingProxyType


class BoardRole(str, Enum):
    """A user's single active role within one Board."""

    CONTRIBUTOR = "contributor"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    MANAGER = "manager"


class BoardAction(str, Enum):
    """Business actions evaluated within a Board boundary."""

    CREATE_POST = "create_post"
    EDIT_OWN_DRAFT = "edit_own_draft"
    EDIT_OWN_POST = "edit_own_post"
    EDIT_ANY_POST = "edit_any_post"
    SUBMIT_POST = "submit_post"
    VIEW_REVIEW_QUEUE = "view_review_queue"
    REVIEW_POST = "review_post"
    PUBLISH_POST = "publish_post"
    MODERATE_COMMENT = "moderate_comment"
    CHANGE_BOARD_SETTINGS = "change_board_settings"
    MANAGE_BOARD_MEMBERS = "manage_board_members"


_CONTRIBUTOR_ACTIONS = frozenset(
    {
        BoardAction.CREATE_POST,
        BoardAction.EDIT_OWN_DRAFT,
        BoardAction.SUBMIT_POST,
    }
)

ROLE_ACTIONS = MappingProxyType(
    {
        BoardRole.CONTRIBUTOR: _CONTRIBUTOR_ACTIONS,
        BoardRole.EDITOR: _CONTRIBUTOR_ACTIONS | {BoardAction.EDIT_OWN_POST},
        BoardRole.REVIEWER: frozenset(
            {
                BoardAction.VIEW_REVIEW_QUEUE,
                BoardAction.REVIEW_POST,
                BoardAction.PUBLISH_POST,
                BoardAction.MODERATE_COMMENT,
            }
        ),
        BoardRole.MANAGER: frozenset(BoardAction),
    }
)


def allows_board_action(
    *,
    role: BoardRole | str | None,
    action: BoardAction | str,
    membership_is_active: bool,
    same_board: bool,
    owns_object: bool = False,
) -> bool:
    """Return whether one Board membership allows an action.

    Superuser bypass and global Django Permissions deliberately live outside this
    function. They will be handled by the Policy adapter in accounts_linear stage 3.
    """
    if not membership_is_active or not same_board or role is None:
        return False

    try:
        normalized_role = BoardRole(role)
        normalized_action = BoardAction(action)
    except ValueError:
        return False

    if normalized_action not in ROLE_ACTIONS[normalized_role]:
        return False
    if normalized_action in {
        BoardAction.EDIT_OWN_DRAFT,
        BoardAction.EDIT_OWN_POST,
    } and not owns_object:
        return False
    if normalized_action in {BoardAction.REVIEW_POST, BoardAction.PUBLISH_POST}:
        return not owns_object
    return True
