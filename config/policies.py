"""Authorization policies for single-site configuration resources."""


def is_site_owner(user) -> bool:
    """Return whether ``user`` owns the single PowerAdapter site.

    Link, SideBar and future site-wide configuration are not multi-author
    content.  Their write boundary is the active superuser, independently of
    which AdminSite or first-party view exposes the action.
    """

    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_superuser", False)
    )
