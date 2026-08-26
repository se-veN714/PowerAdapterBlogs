"""Bounded, read-only queries for Mongo-authoritative audit evidence."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Callable, Mapping

from pymongo import DESCENDING

from security.audit import PUBLIC_EVENT_FIELDS
from security.mongo_client import MongoLogger


FILTER_PATTERN = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$")


@dataclass(frozen=True)
class AuditQueryPage:
    items: tuple[dict, ...]
    next_cursor: str | None
    limit: int


def _filter_value(name: str, value) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not FILTER_PATTERN.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _encode_cursor(occurred_at: str, event_id: str) -> str:
    raw = json.dumps([occurred_at, event_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError("invalid cursor")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(value + padding))
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("invalid cursor") from None
    if (
        not isinstance(decoded, list)
        or len(decoded) != 2
        or not all(isinstance(item, str) and item for item in decoded)
    ):
        raise ValueError("invalid cursor")
    return decoded[0], decoded[1]


def _public_event(document: Mapping, verification) -> dict:
    event = {field: document[field] for field in PUBLIC_EVENT_FIELDS if field in document}
    event["verification"] = {
        "valid": bool(verification.valid),
        "reason": str(verification.reason),
    }
    return event


def query_audit_events(
    *,
    collection=None,
    verifier: Callable | None = None,
    event_type=None,
    actor_id=None,
    target_type=None,
    target_id=None,
    partition=None,
    cursor=None,
    limit=50,
) -> AuditQueryPage:
    """Query only schema-v1 Mongo evidence; never read relational outbox payloads."""
    if collection is None:
        mongo = MongoLogger()
        collection = mongo.collection
        verifier = mongo.verify_log
    elif verifier is None:
        raise ValueError("a verifier is required with an injected collection")
    try:
        bounded_limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        raise ValueError("invalid limit") from None

    query = {"schema_version": 1}
    filters = {
        "event_type": _filter_value("event_type", event_type),
        "actor.id": _filter_value("actor_id", actor_id),
        "target.type": _filter_value("target_type", target_type),
        "target.id": _filter_value("target_id", target_id),
        "integrity.partition": _filter_value("partition", partition),
    }
    query.update({field: value for field, value in filters.items() if value is not None})
    if cursor:
        occurred_at, event_id = _decode_cursor(cursor)
        query["$or"] = [
            {"occurred_at": {"$lt": occurred_at}},
            {"occurred_at": occurred_at, "_id": {"$lt": event_id}},
        ]

    projection = {field: 1 for field in PUBLIC_EVENT_FIELDS}
    documents = list(
        collection.find(query, projection)
        .sort([("occurred_at", DESCENDING), ("_id", DESCENDING)])
        .limit(bounded_limit)
        .batch_size(min(bounded_limit, 200))
    )
    items = tuple(_public_event(document, verifier(document)) for document in documents)
    next_cursor = None
    if len(items) == bounded_limit:
        occurred_at = items[-1].get("occurred_at")
        event_id = items[-1].get("_id")
        if isinstance(occurred_at, str) and isinstance(event_id, str):
            next_cursor = _encode_cursor(occurred_at, event_id)
    return AuditQueryPage(items=items, next_cursor=next_cursor, limit=bounded_limit)
