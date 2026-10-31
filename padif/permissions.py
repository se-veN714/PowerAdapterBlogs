from typing import Protocol


class PadifUser(Protocol):
    is_authenticated: bool
    is_active: bool
    is_superuser: bool

    def has_perm(self, perm: str) -> bool: ...


def can_use_padif(user: PadifUser) -> bool:
    """Keep authentication and global PAdif capability separate."""
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.is_superuser or user.has_perm("padif.use_padif"))
    )
