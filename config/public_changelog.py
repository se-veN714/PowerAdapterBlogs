"""Validated, public-safe release notes for the Changelog page."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


SCHEMA_VERSION = 1
ALLOWED_TAGS = frozenset({"GENERAL", "SK8", "MUSIC", "CODE"})
ALLOWED_STATUSES = frozenset({"CURRENT", "STABLE"})


def _required_text(release, field, *, index):
    value = release.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ImproperlyConfigured(
            f"Public changelog release {index} requires non-empty {field}."
        )
    return value.strip()


def _validate_release(release, *, index):
    if not isinstance(release, dict):
        raise ImproperlyConfigured(
            f"Public changelog release {index} must be an object."
        )

    version = _required_text(release, "version", index=index)
    raw_date = _required_text(release, "date", index=index)
    try:
        published_on = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"Public changelog release {index} has an invalid ISO date."
        ) from exc
    if version != raw_date.replace("-", "."):
        raise ImproperlyConfigured(
            f"Public changelog release {index} version must match its date."
        )

    status = _required_text(release, "status", index=index)
    if status not in ALLOWED_STATUSES:
        raise ImproperlyConfigured(
            f"Public changelog release {index} has an unsupported status."
        )

    tags = release.get("tags")
    if (
        not isinstance(tags, list)
        or not tags
        or any(tag not in ALLOWED_TAGS for tag in tags)
        or len(tags) != len(set(tags))
    ):
        raise ImproperlyConfigured(
            f"Public changelog release {index} has invalid or duplicate tags."
        )

    details = release.get("details")
    if (
        not isinstance(details, list)
        or not details
        or len(details) > 3
        or any(not isinstance(item, str) or not item.strip() for item in details)
    ):
        raise ImproperlyConfigured(
            f"Public changelog release {index} requires one to three details."
        )

    return {
        "version": version,
        "date": raw_date,
        "published_on": published_on,
        "status": status,
        "title": _required_text(release, "title", index=index),
        "summary": _required_text(release, "summary", index=index),
        "tags": tuple(tags),
        "details": tuple(item.strip() for item in details),
    }


@lru_cache(maxsize=1)
def load_public_changelog():
    """Load the curated public timeline; never expose the engineering log."""
    path = Path(settings.BASE_DIR) / "config" / "data" / "public_changelog.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImproperlyConfigured("Public changelog data could not be loaded.") from exc

    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ImproperlyConfigured("Unsupported public changelog schema version.")

    raw_releases = payload.get("releases")
    if not isinstance(raw_releases, list) or not raw_releases:
        raise ImproperlyConfigured("Public changelog requires at least one release.")

    releases = tuple(
        _validate_release(release, index=index)
        for index, release in enumerate(raw_releases, start=1)
    )
    if tuple(item["published_on"] for item in releases) != tuple(
        sorted((item["published_on"] for item in releases), reverse=True)
    ):
        raise ImproperlyConfigured("Public changelog releases must be newest first.")
    if releases[0]["status"] != "CURRENT" or any(
        item["status"] == "CURRENT" for item in releases[1:]
    ):
        raise ImproperlyConfigured(
            "Public changelog must have exactly one current release at the top."
        )
    return releases
