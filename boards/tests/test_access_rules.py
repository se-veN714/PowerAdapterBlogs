"""Contract tests for Board-scoped role decisions."""

from django.test import SimpleTestCase

from boards.access_rules import BoardAction, BoardRole, allows_board_action


class BoardAccessRulesTest(SimpleTestCase):
    """Freeze the accounts_linear stage 0 role matrix and denial rules."""

    def assert_allowed(self, role, action, *, owns_object=False):
        self.assertTrue(
            allows_board_action(
                role=role,
                action=action,
                membership_is_active=True,
                same_board=True,
                owns_object=owns_object,
            )
        )

    def assert_denied(self, role, action, **overrides):
        context = {
            "membership_is_active": True,
            "same_board": True,
            "owns_object": False,
        }
        context.update(overrides)
        self.assertFalse(allows_board_action(role=role, action=action, **context))

    def test_contributor_can_submit_and_edit_only_own_post(self):
        self.assert_allowed(BoardRole.CONTRIBUTOR, BoardAction.CREATE_POST)
        self.assert_allowed(
            BoardRole.CONTRIBUTOR,
            BoardAction.EDIT_OWN_DRAFT,
            owns_object=True,
        )
        self.assert_allowed(
            BoardRole.CONTRIBUTOR,
            BoardAction.SUBMIT_POST,
            owns_object=True,
        )
        self.assert_denied(BoardRole.CONTRIBUTOR, BoardAction.EDIT_OWN_DRAFT)
        self.assert_denied(BoardRole.CONTRIBUTOR, BoardAction.SUBMIT_POST)
        self.assert_denied(
            BoardRole.CONTRIBUTOR,
            BoardAction.EDIT_OWN_POST,
            owns_object=True,
        )
        self.assert_denied(BoardRole.CONTRIBUTOR, BoardAction.REVIEW_POST)

    def test_editor_can_edit_own_post_but_not_another_authors_post(self):
        self.assert_allowed(
            BoardRole.EDITOR,
            BoardAction.EDIT_OWN_POST,
            owns_object=True,
        )
        self.assert_denied(BoardRole.EDITOR, BoardAction.EDIT_ANY_POST)
        self.assert_denied(BoardRole.EDITOR, BoardAction.REVIEW_POST)

    def test_reviewer_can_review_but_cannot_edit_content(self):
        self.assert_allowed(BoardRole.REVIEWER, BoardAction.VIEW_REVIEW_QUEUE)
        self.assert_allowed(BoardRole.REVIEWER, BoardAction.REVIEW_POST)
        self.assert_allowed(BoardRole.REVIEWER, BoardAction.MODERATE_COMMENT)
        self.assert_denied(BoardRole.REVIEWER, BoardAction.EDIT_OWN_DRAFT)
        self.assert_denied(BoardRole.REVIEWER, BoardAction.EDIT_OWN_POST)
        self.assert_denied(BoardRole.REVIEWER, BoardAction.EDIT_ANY_POST)

    def test_reviewer_and_manager_cannot_review_their_own_post(self):
        for role in (BoardRole.REVIEWER, BoardRole.MANAGER):
            with self.subTest(role=role):
                self.assert_denied(
                    role,
                    BoardAction.REVIEW_POST,
                    owns_object=True,
                )
                self.assert_denied(
                    role,
                    BoardAction.PUBLISH_POST,
                    owns_object=True,
                )

    def test_membership_never_grants_access_to_another_board(self):
        for role in BoardRole:
            with self.subTest(role=role):
                self.assert_denied(
                    role,
                    BoardAction.CREATE_POST,
                    same_board=False,
                )

    def test_inactive_membership_grants_no_actions(self):
        for action in BoardAction:
            with self.subTest(action=action):
                self.assert_denied(
                    BoardRole.MANAGER,
                    action,
                    membership_is_active=False,
                )

    def test_unknown_role_or_action_fails_closed(self):
        self.assert_denied("unknown", BoardAction.CREATE_POST)
        self.assert_denied(BoardRole.MANAGER, "unknown")
