"""Deep import module for normalized, deployment-safe music aggregates."""

import json

from django.core.management.base import CommandError

from boards.models import (
    AppleRecord,
    MusicArtist,
    MusicScope,
    SpotifyRecord,
    normalize_music_artist_name,
)


PROVIDER_MODELS = {"spotify": SpotifyRecord, "apple": AppleRecord}
PROVIDER_URL_FIELDS = {"spotify": "spotify_url", "apple": "apple_music_url"}
RANKED_KINDS = {"top_artist", "top_track", "core_artist", "period_artist"}
IMPORT_FIELDS = {
    "title", "scope", "year", "month", "label", "value", "value2",
    "unit", "kind", "note", "rank", "play_count", "minutes",
    "external_url", "display_order",
}


def load_music_payload(path, provider):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CommandError(f"Music records file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CommandError(f"Invalid music records JSON: {path.name}") from exc
    if payload.get("schema_version") != 1 or payload.get("provider") != provider:
        raise CommandError(f"Expected schema_version=1 and provider={provider}")
    if not isinstance(payload.get("records"), list):
        raise CommandError("Music records JSON must contain a records array")
    return payload["records"]


def validate_music_record(raw, index):
    if not isinstance(raw, dict):
        raise CommandError(f"Record {index} must be an object")
    unknown = set(raw) - IMPORT_FIELDS - {"artist_name"}
    if unknown:
        raise CommandError(f"Record {index} has unsupported fields: {sorted(unknown)}")
    data = {field: raw[field] for field in IMPORT_FIELDS if field in raw}
    required = {"title", "scope", "year", "kind", "label", "value"}
    missing = required - set(data)
    if missing:
        raise CommandError(f"Record {index} is missing fields: {sorted(missing)}")
    if data["scope"] not in MusicScope.values:
        raise CommandError(f"Record {index} has an invalid scope")
    month = data.get("month")
    if data["scope"] == MusicScope.MONTHLY and not (
        isinstance(month, int) and 1 <= month <= 12
    ):
        raise CommandError(f"Record {index} is monthly but has no valid month")
    if data["scope"] == MusicScope.YEARLY:
        data["month"] = None
    if data["kind"] in RANKED_KINDS and not data.get("rank"):
        raise CommandError(f"Record {index} requires rank for kind={data['kind']}")
    artist_name = raw.get("artist_name")
    if artist_name is not None:
        artist_name = str(artist_name).strip()
    return data, artist_name


def _identity_queryset(model, board, data):
    queryset = model.objects.filter(
        board=board, scope=data["scope"], year=data["year"],
        month=data.get("month"), kind=data["kind"],
    )
    if data["kind"] in RANKED_KINDS:
        return queryset.filter(rank=data["rank"])
    return queryset.filter(label=data["label"])


def _resolve_artist(board, provider, name, external_url):
    if not name:
        return None
    artist, _ = MusicArtist.objects.get_or_create(
        board=board,
        normalized_name=normalize_music_artist_name(name),
        defaults={"name": name},
    )
    url_field = PROVIDER_URL_FIELDS[provider]
    if external_url and not getattr(artist, url_field):
        setattr(artist, url_field, external_url)
        artist.save(update_fields=[url_field, "updated_at"])
    return artist


def import_music_records(*, board, provider, records):
    """Synchronize declared records without pruning undeclared narrative rows."""
    model = PROVIDER_MODELS[provider]
    created = updated = deduplicated = 0
    for index, raw in enumerate(records, start=1):
        data, artist_name = validate_music_record(raw, index)
        artist = None
        if artist_name is not None:
            artist = _resolve_artist(
                board,
                provider,
                artist_name,
                data.get("external_url", "")
                if data["kind"] != "top_track"
                else "",
            )
        matches = _identity_queryset(model, board, data).order_by("pk")
        target = matches.first()
        if target is None:
            model.objects.create(board=board, artist=artist, **data)
            created += 1
            continue
        changed_fields = []
        for field, value in data.items():
            if getattr(target, field) != value:
                setattr(target, field, value)
                changed_fields.append(field)
        if artist_name is not None and target.artist_id != (
            artist.pk if artist else None
        ):
            target.artist = artist
            changed_fields.append("artist")
        if changed_fields:
            target.save(update_fields=[*changed_fields, "updated_at"])
            updated += 1
        duplicate_count, _ = matches.exclude(pk=target.pk).delete()
        deduplicated += duplicate_count
    return {"created": created, "updated": updated, "deduplicated": deduplicated}
