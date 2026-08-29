import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock
from uuid import UUID, uuid4

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from pymongo.errors import OperationFailure

from accounts.models import MyUser
from security.audit import (
    AuditKeyring,
    create_signed_event,
    verify_chain,
    verify_document,
)
from security.models import AuditOutbox, SecureLogEntry
from security.mongo_client import AuditDeliveryConflict, MongoLogger
from security.outbox import (
    AuditEventCollision,
    deliver_outbox_batch,
    enqueue_audit_event,
    reconcile_delivered_outbox,
)


def test_key(label):
    return hashlib.sha256(f"test-only:{label}".encode()).digest()


KEYRING = AuditKeyring(
    domain="mongo",
    active_key_id="mongo-v1",
    keys={"mongo-v1": test_key("mongo"), "legacy": test_key("legacy")},
    legacy_key_id="legacy",
)


def signed_event(*, event_id, sequence=1, previous_mac=None, change=None):
    return create_signed_event(
        event_type="comment.moderated",
        actor={"type": "user", "id": "7"},
        target={"type": "comment", "id": "42"},
        change=change or {"before": {"status": 0}, "after": {"status": 1}},
        outcome={"status": "success", "error_code": None},
        context={"source": "web"},
        event_id=event_id,
        occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
        partition="comment:2026-08",
        sequence=sequence,
        previous_mac=previous_mac,
        keyring=KEYRING,
    )


class CanonicalAuditTests(SimpleTestCase):
    def test_full_envelope_tampering_fails(self):
        document = signed_event(event_id="00000000-0000-4000-8000-000000000001")
        self.assertTrue(verify_document(document, KEYRING).valid)
        for field, value in (
            ("event_type", "comment.deleted"),
            ("occurred_at", "2026-08-27T00:00:00.000000Z"),
        ):
            changed = deepcopy(document)
            changed[field] = value
            self.assertFalse(verify_document(changed, KEYRING).valid)

    def test_checkpoint_still_anchors_chain_after_later_events(self):
        original_first = signed_event(
            event_id="00000000-0000-4000-8000-000000000011"
        )
        checkpoint = {
            "partition": "comment:2026-08",
            "sequence": 1,
            "mac": original_first["integrity"]["mac"],
        }
        rewritten_first = signed_event(
            event_id="00000000-0000-4000-8000-000000000011",
            change={"before": {"status": 0}, "after": {"status": 2}},
        )
        rewritten_second = signed_event(
            event_id="00000000-0000-4000-8000-000000000012",
            sequence=2,
            previous_mac=rewritten_first["integrity"]["mac"],
        )
        result = verify_chain(
            [rewritten_first, rewritten_second],
            KEYRING,
            checkpoint=checkpoint,
        )
        self.assertIn("checkpoint_mac_mismatch", result.errors)


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def with_transaction(self, callback):
        return callback(self)


class _FakeClient:
    def start_session(self):
        return _FakeSession()


class _FakeEvents:
    def __init__(self):
        self.documents = {}

    def find_one(self, query, session=None):
        return deepcopy(self.documents.get(query["_id"]))

    def insert_one(self, document, session=None):
        self.documents[document["_id"]] = deepcopy(document)


class _FakeHeads:
    def __init__(self):
        self.documents = {}

    def find_one_and_update(self, query, update, **kwargs):
        partition = query["_id"]
        previous = deepcopy(self.documents.get(partition))
        current = self.documents.setdefault(partition, {"_id": partition, "sequence": 0})
        current["sequence"] += update["$inc"]["sequence"]
        return previous

    def update_one(self, query, update, session=None):
        current = self.documents[query["_id"]]
        if current["sequence"] != query["sequence"]:
            return SimpleNamespace(matched_count=0)
        current.update(update["$set"])
        return SimpleNamespace(matched_count=1)


class MongoIdempotencyTests(SimpleTestCase):
    def writer(self):
        writer = MongoLogger.__new__(MongoLogger)
        writer.client = _FakeClient()
        writer.collection = _FakeEvents()
        writer.heads = _FakeHeads()
        writer.keyring = KEYRING
        return writer

    def event(self):
        return {
            "schema_version": 1,
            "event_id": "00000000-0000-4000-8000-000000000041",
            "event_type": "comment.moderated",
            "occurred_at": "2026-08-26T00:00:00.000000Z",
            "actor": {"type": "user", "id": "7"},
            "target": {"type": "comment", "id": "42"},
            "context": {"source": "web"},
            "change": {"before": {"status": 0}, "after": {"status": 1}},
            "outcome": {"status": "success", "error_code": None},
        }

    def test_partition_is_part_of_idempotent_identity(self):
        writer = self.writer()
        event = self.event()
        writer.insert_event(event, partition="comment:2026-08")
        with self.assertRaises(AuditDeliveryConflict):
            writer.insert_event(event, partition="comment:2026-09")

    def test_direct_legacy_write_is_blocked(self):
        with self.assertRaises(RuntimeError):
            self.writer().insert_log("legacy", {"sensitive": "payload"})

    def test_index_setup_creates_head_namespace_without_collection_preflight(self):
        writer = MongoLogger.__new__(MongoLogger)
        writer.collection = mock.Mock()
        writer.heads = SimpleNamespace(name="audit_chain_heads")
        writer.db = mock.Mock()

        writer.ensure_indexes()

        writer.db.command.assert_called_once_with("create", "audit_chain_heads")

    def test_index_setup_accepts_existing_head_namespace(self):
        writer = MongoLogger.__new__(MongoLogger)
        writer.collection = mock.Mock()
        writer.heads = SimpleNamespace(name="audit_chain_heads")
        writer.db = mock.Mock()
        writer.db.command.side_effect = OperationFailure(
            "namespace already exists", code=48
        )

        writer.ensure_indexes()


@override_settings(
    MONGO_AUDIT_HMAC_KEYS={"mongo-v1": test_key("mongo")},
    MONGO_AUDIT_ACTIVE_KEY_ID="mongo-v1",
)
class OutboxSafetyTests(TestCase):
    def enqueue(self, *, event_id=None, occurred_at=None, partition=None):
        return enqueue_audit_event(
            event_id=event_id,
            occurred_at=occurred_at,
            partition=partition,
            event_type="test.changed",
            actor={"type": "system", "id": "test"},
            target={"type": "test", "id": "1"},
            change={"before": {}, "after": {"state": "changed"}},
        )

    def test_explicit_time_or_partition_change_causes_collision(self):
        event_id = UUID("00000000-0000-4000-8000-000000000021")
        occurred = datetime(2026, 8, 26, tzinfo=UTC)
        first = self.enqueue(
            event_id=event_id,
            occurred_at=occurred,
            partition="test:2026-08",
        )
        duplicate = self.enqueue(event_id=event_id)
        self.assertEqual(first.pk, duplicate.pk)
        with self.assertRaises(AuditEventCollision):
            self.enqueue(
                event_id=event_id,
                occurred_at=datetime(2026, 8, 27, tzinfo=UTC),
                partition="test:2026-08",
            )
        with self.assertRaises(AuditEventCollision):
            self.enqueue(
                event_id=event_id,
                occurred_at=occurred,
                partition="test:2026-09",
            )

    def test_missing_receipt_is_retryable_not_delivered(self):
        row = self.enqueue()
        writer = mock.Mock()
        writer.insert_event.return_value = None
        result = deliver_outbox_batch(writer=writer, limit=1)
        row.refresh_from_db()
        self.assertEqual(result.failed, 1)
        self.assertEqual(row.status, AuditOutbox.Status.PENDING)
        self.assertEqual(row.last_error_code, "InvalidAuditReceipt")

    def test_expired_worker_cannot_overwrite_new_lease(self):
        row = self.enqueue()
        new_token = uuid4()

        def steal_lease(*args, **kwargs):
            AuditOutbox.objects.filter(pk=row.pk).update(
                status=AuditOutbox.Status.PROCESSING,
                lock_token=new_token,
                locked_at=timezone.now(),
            )
            return {
                "integrity": {
                    "partition": row.partition,
                    "sequence": 1,
                    "mac": "valid-receipt",
                }
            }

        writer = mock.Mock()
        writer.insert_event.side_effect = steal_lease
        result = deliver_outbox_batch(writer=writer, limit=1)
        row.refresh_from_db()
        self.assertEqual(result.lost_leases, 1)
        self.assertEqual(row.lock_token, new_token)
        self.assertEqual(row.status, AuditOutbox.Status.PROCESSING)

    def test_reconciliation_detects_missing_authority_record(self):
        row = self.enqueue()
        AuditOutbox.objects.filter(pk=row.pk).update(
            status=AuditOutbox.Status.DELIVERED,
            delivery_sequence=1,
            delivery_mac="receipt",
        )
        writer = SimpleNamespace(
            collection=SimpleNamespace(find_one=lambda query: None),
            keyring=KEYRING,
        )
        result = reconcile_delivered_outbox(writer=writer)
        self.assertFalse(result.healthy)
        self.assertEqual(result.missing, 1)


class AdminAuthorityTests(TestCase):
    def setUp(self):
        self.user = MyUser.objects.create_user(
            email="audit@example.test",
            username="audit-user",
            password="test-password",
            is_active=True,
        )
        self.content_type = ContentType.objects.get_for_model(MyUser)

    def test_new_admin_history_uses_outbox_not_legacy_signature(self):
        entry = LogEntry.objects.log_action(
            user_id=self.user.pk,
            content_type_id=self.content_type.pk,
            object_id=str(self.user.pk),
            object_repr=str(self.user),
            action_flag=CHANGE,
            change_message=[{"changed": {"fields": ["groups"]}}],
        )

        row = AuditOutbox.objects.get(
            event_type="django_admin.object.changed",
            event__target__id=str(self.user.pk),
        )
        self.assertEqual(row.event["change"], {"fields": ["groups"]})
        self.assertFalse(SecureLogEntry.objects.filter(log_entry=entry).exists())

    def test_bulk_admin_history_is_fully_enqueued(self):
        other = MyUser.objects.create_user(
            email="other-audit@example.test",
            username="other-audit-user",
            password="test-password",
            is_active=True,
        )
        LogEntry.objects.log_actions(
            user_id=self.user.pk,
            queryset=[self.user, other],
            action_flag=CHANGE,
            change_message="bulk change",
        )

        self.assertEqual(
            AuditOutbox.objects.filter(
                event_type="django_admin.object.changed"
            ).count(),
            2,
        )

    def test_outbox_failure_rolls_back_admin_history(self):
        with self.assertRaises(RuntimeError), mock.patch(
            "security.admin_audit.enqueue_audit_event",
            side_effect=RuntimeError("outbox unavailable"),
        ), transaction.atomic():
            LogEntry.objects.create(
                user=self.user,
                content_type=self.content_type,
                object_id=str(self.user.pk),
                object_repr=str(self.user),
                action_flag=CHANGE,
                change_message="changed",
            )

        self.assertFalse(LogEntry.objects.exists())
