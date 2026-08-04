"""PostgreSQL-only race contracts for Membership governance invariants."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import OperationalError, close_old_connections, connection
from django.test import TransactionTestCase, skipUnlessDBFeature

from accounts.models import MyUser
from boards.models import Board, BoardMembership, BoardMembershipEvent
from boards.services import deactivate_board_membership


class MembershipPostgresConcurrencyTest(TransactionTestCase):
    """Run against PostgreSQL; SQLite cannot exercise row-lock semantics."""

    reset_sequences = True

    def setUp(self):
        self.actor = MyUser.objects.create_superuser(
            email="concurrency-root@example.test",
            username="concurrency-root",
            password="test-only-password",
        )
        self.board = Board.objects.create(slug="race-board", name="Race Board")
        self.managers = []
        for index in range(2):
            user = MyUser.objects.create_user(
                email=f"race-manager-{index}@example.test",
                username=f"race-manager-{index}",
                password="test-only-password",
                is_active=True,
            )
            self.managers.append(
                BoardMembership.objects.create(
                    board=self.board,
                    user=user,
                    role=BoardMembership.Role.MANAGER,
                    created_by=self.actor,
                )
            )

    def _deactivate_at_barrier(self, membership_id, barrier):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            membership = BoardMembership.objects.get(pk=membership_id)
            deactivate_board_membership(
                request=SimpleNamespace(user=self.actor),
                actor=self.actor,
                membership=membership,
                reason="Concurrent manager removal test",
                capability=None,
            )
            return "committed"
        except ValidationError:
            return "rejected"
        except OperationalError:
            # PostgreSQL may choose a deadlock victim. That is a safe failure
            # provided the governance invariant remains intact.
            return "database-conflict"
        finally:
            close_old_connections()

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_manager_deactivations_cannot_create_zero_manager_board(self):
        if connection.vendor != "postgresql":
            self.skipTest("This contract requires PostgreSQL row locks.")
        barrier = threading.Barrier(2)
        with patch("boards.services._consume_dashboard_step_up", return_value=None):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(
                    executor.map(
                        lambda membership: self._deactivate_at_barrier(
                            membership.pk,
                            barrier,
                        ),
                        self.managers,
                    )
                )

        active_managers = BoardMembership.objects.filter(
            board=self.board,
            role=BoardMembership.Role.MANAGER,
            is_active=True,
        ).count()
        self.assertGreaterEqual(active_managers, 1)
        self.assertLessEqual(results.count("committed"), 1)
        self.assertEqual(
            BoardMembershipEvent.objects.filter(
                board=self.board,
                event_type=BoardMembershipEvent.EventType.DEACTIVATED,
            ).count(),
            results.count("committed"),
        )
