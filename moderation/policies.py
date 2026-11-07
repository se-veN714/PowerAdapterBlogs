from boards.policies import (
    can_access_board_admin,
    can_access_comment_admin,
    can_review_posts_in_admin,
)


def can_review_accounts(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and (
            getattr(user, "is_superuser", False)
            or user.has_perm("accounts.manage_user_accounts")
        )
    )


def moderation_capabilities(user) -> dict[str, bool]:
    from agent_mcp.access import can_review_agents
    return {
        "agents": can_review_agents(user),
        "accounts": can_review_accounts(user),
        "posts": can_review_posts_in_admin(user),
        "comments": can_access_comment_admin(user),
        "boards": can_access_board_admin(user),
    }


def can_access_moderation_center(user) -> bool:
    return any(moderation_capabilities(user).values())
