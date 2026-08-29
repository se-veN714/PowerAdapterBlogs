"""MongoDB transport for versioned, chained, immutable audit events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

from django.conf import settings
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import OperationFailure

from security.audit import (
    IMMUTABLE_EVENT_FIELDS,
    AuditKeyring,
    canonical_json_bytes,
    create_signed_event,
    verify_chain,
    verify_document,
)


def dict_to_bytes(data: dict) -> bytes:
    """Historical canonicalization retained only for legacy verification."""
    return canonical_json_bytes(data, legacy=True)


class AuditDeliveryConflict(RuntimeError):
    pass


class AuditMongoDeploymentError(RuntimeError):
    def __init__(self, *reason_codes: str):
        self.reason_codes = tuple(sorted(set(reason_codes)))
        super().__init__(",".join(self.reason_codes))


class MongoLogger:
    """The sole transport for Mongo-authoritative audit evidence.

    Chain insertion requires transactions, hence a replica set or sharded
    cluster. Transport failures propagate so the relational outbox can retry.
    """

    def __init__(self, *, client=None, keyring: AuditKeyring | None = None):
        conf = settings.MONGO
        if client is None:
            connection = {
                "host": conf["HOST"],
                "port": int(conf["PORT"]),
                "serverSelectionTimeoutMS": int(
                    conf.get("SERVER_SELECTION_TIMEOUT_MS", 3000)
                ),
            }
            if conf.get("DB_USER") and conf.get("DB_PASSWORD"):
                connection.update(
                    username=conf["DB_USER"],
                    password=conf["DB_PASSWORD"],
                    authSource=conf.get("AUTH_SOURCE") or conf["DB_NAME"],
                )
            if conf.get("REPLICA_SET"):
                connection["replicaSet"] = conf["REPLICA_SET"]
            client = MongoClient(**connection)
        self.client = client
        self.db = client[conf["DB_NAME"]]
        self.collection = self.db[conf.get("COLLECTION", "audit_events")]
        self.heads = self.db[conf.get("HEAD_COLLECTION", "audit_chain_heads")]
        self.keyring = keyring or AuditKeyring.from_settings("mongo")

    @property
    def connected(self) -> bool:
        """Compatibility indicator; actual operations still fail explicitly."""
        return self.client is not None

    def close(self):
        if self.client is not None:
            self.client.close()

    def ensure_indexes(self):
        self.collection.create_index(
            [("event_id", ASCENDING)], unique=True, name="audit_event_id_unique"
        )
        self.collection.create_index(
            [("integrity.partition", ASCENDING), ("integrity.sequence", ASCENDING)],
            unique=True,
            name="audit_partition_sequence_unique",
        )
        self.collection.create_index(
            [("schema_version", ASCENDING), ("occurred_at", DESCENDING), ("_id", DESCENDING)],
            name="audit_query_recent",
        )
        self.collection.create_index(
            [("event_type", ASCENDING), ("occurred_at", DESCENDING), ("_id", DESCENDING)],
            name="audit_query_event_type",
        )
        self.collection.create_index(
            [("actor.id", ASCENDING), ("occurred_at", DESCENDING), ("_id", DESCENDING)],
            name="audit_query_actor",
        )
        self.collection.create_index(
            [
                ("target.type", ASCENDING),
                ("target.id", ASCENDING),
                ("occurred_at", DESCENDING),
                ("_id", DESCENDING),
            ],
            name="audit_query_target",
        )
        # `check_deployment()` also inspects the chain-head collection. On a
        # fresh database no delivery has created it yet, so establish the
        # namespace explicitly without granting the deploy role event writes.
        # Use the raw command because PyMongo's create_collection helper performs
        # a `listCollections` preflight. The deploy role intentionally lacks that
        # broader database-wide privilege.
        try:
            self.db.command("create", self.heads.name)
        except OperationFailure as exc:
            if exc.code != 48:  # NamespaceExists
                raise

    def check_deployment(self) -> dict[str, str]:
        hello = self.db.command("hello")
        if hello.get("setName"):
            topology = "replica_set"
        elif hello.get("msg") == "isdbgrid":
            topology = "sharded_cluster"
        else:
            raise AuditMongoDeploymentError("transactions_required")

        event_indexes = self.collection.index_information()
        head_indexes = self.heads.index_information()
        reasons = []
        if any(
            "expireAfterSeconds" in spec
            for spec in (*event_indexes.values(), *head_indexes.values())
        ):
            reasons.append("ttl_forbidden")
        required_unique = {
            (("event_id", 1),),
            (("integrity.partition", 1), ("integrity.sequence", 1)),
        }
        actual_unique = {
            tuple((str(field), int(direction)) for field, direction in spec.get("key", []))
            for spec in event_indexes.values()
            if spec.get("unique")
        }
        if not required_unique.issubset(actual_unique):
            reasons.append("required_unique_index_missing")
        if reasons:
            raise AuditMongoDeploymentError(*reasons)
        return {"topology": topology, "status": "ready"}

    def insert_event(self, event: Mapping[str, Any], *, partition: str) -> dict[str, Any]:
        """Idempotently append one canonical outbox event to its partition."""
        event_id = str(event["event_id"])

        def append(session):
            existing = self.collection.find_one({"_id": event_id}, session=session)
            if existing is not None:
                verification = verify_document(existing, self.keyring)
                same_event = all(
                    existing.get(field) == event.get(field)
                    for field in IMMUTABLE_EVENT_FIELDS
                )
                same_partition = existing.get("integrity", {}).get("partition") == partition
                if not verification.valid or not same_event or not same_partition:
                    raise AuditDeliveryConflict(
                        "event_id already exists with different or invalid canonical content"
                    )
                return existing

            previous = self.heads.find_one_and_update(
                {"_id": partition},
                {"$inc": {"sequence": 1}},
                upsert=True,
                return_document=ReturnDocument.BEFORE,
                session=session,
            )
            sequence = int(previous.get("sequence", 0)) + 1 if previous else 1
            previous_mac = previous.get("last_mac") if previous else None
            document = create_signed_event(
                event_type=event["event_type"],
                actor=event["actor"],
                target=event["target"],
                change=event["change"],
                outcome=event["outcome"],
                context=event["context"],
                event_id=event_id,
                occurred_at=event["occurred_at"],
                ingested_at=datetime.now(UTC),
                partition=partition,
                sequence=sequence,
                previous_mac=previous_mac,
                keyring=self.keyring,
            )
            self.collection.insert_one(document, session=session)
            result = self.heads.update_one(
                {"_id": partition, "sequence": sequence},
                {"$set": {"last_mac": document["integrity"]["mac"], "event_id": event_id}},
                session=session,
            )
            if result.matched_count != 1:
                raise AuditDeliveryConflict("audit chain head changed unexpectedly")
            return document

        with self.client.start_session() as session:
            return session.with_transaction(append)

    def insert_log(self, action: str, data: dict):
        """Block the old direct-write API so callers cannot bypass the outbox."""
        raise RuntimeError(
            "direct Mongo audit writes are disabled; use security.outbox.enqueue_audit_event"
        )

    def verify_log(self, document: Mapping[str, Any]):
        return verify_document(document, self.keyring)

    def iter_partition(
        self,
        partition: str,
        *,
        limit: int = 10000,
        after_sequence: int = 0,
    ):
        bounded = max(1, min(limit, 100000))
        query = {
            "integrity.partition": partition,
            "integrity.sequence": {"$gt": after_sequence},
        }
        return (
            self.collection.find(query)
            .sort("integrity.sequence", ASCENDING)
            .limit(bounded)
            .batch_size(min(500, bounded))
        )

    def audit_partition(self, partition: str, *, limit: int = 10000, checkpoint=None):
        return verify_chain(
            self.iter_partition(partition, limit=limit),
            self.keyring,
            checkpoint=checkpoint,
        )

    def get_chain_head(self, partition: str):
        head = self.heads.find_one({"_id": partition})
        if not head:
            return None
        return {
            "partition": partition,
            "sequence": int(head["sequence"]),
            "mac": head.get("last_mac"),
        }
