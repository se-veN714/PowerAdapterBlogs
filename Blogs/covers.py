"""Presentation-neutral category to default-cover mapping."""

GENERIC_DEFAULT_COVER = "img/Cover.png"

_CATEGORY_COVER_RULES = (
    (("coding", "code", "编程", "编码"), "img/covers/default-code.webp"),
    (("music", "音乐"), "img/covers/default-music.webp"),
    (("skateboard", "skate", "滑板"), "img/covers/default-skate.webp"),
    (("rhizome", "块茎"), "img/covers/default-rhizome.webp"),
    (("noise", "噪声"), "img/covers/default-noise.webp"),
)


def default_cover_static_path(category_name: str) -> str:
    """Return a static path without turning a default into an uploaded file."""
    normalized_name = str(category_name or "").casefold()
    for aliases, static_path in _CATEGORY_COVER_RULES:
        if any(alias in normalized_name for alias in aliases):
            return static_path
    return GENERIC_DEFAULT_COVER
