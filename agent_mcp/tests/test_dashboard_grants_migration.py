"""Management metadata must preserve historical eligibility and applications."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class DashboardGrantMigrationTests(TransactionTestCase):
    def test_existing_qualifications_and_requests_are_preserved(self):
        old = ('agent_mcp', '0004_alter_agentaccessrequest_reason')
        new = ('agent_mcp', '0005_agentqualification_managed_by_and_more')
        executor = MigrationExecutor(connection)
        executor.migrate([old])
        apps = executor.loader.project_state([old]).apps
        try:
            user = get_user_model().objects.create_user(username='historical-agent', email='historical-agent@example.test', password='unused')
            model = apps.get_model('agent_mcp', 'AgentQualification')
            model.objects.create(user_id=user.pk, revision=7, is_active=False, revoked_at=timezone.now())
            apps.get_model('agent_mcp', 'AgentAccessRequest').objects.create(applicant_id=user.pk, status='approved', decision_note='Historical approval')
            before_grants = list(model.objects.values())
            before_requests = list(apps.get_model('agent_mcp', 'AgentAccessRequest').objects.values())
            executor = MigrationExecutor(connection)
            executor.migrate([new])
            current = executor.loader.project_state([new]).apps
            rows = list(current.get_model('agent_mcp', 'AgentQualification').objects.values())
            for row in rows:
                self.assertEqual(row.pop('management_note'), '')
                self.assertIsNone(row.pop('managed_by_id'))
            self.assertEqual(rows, before_grants)
            self.assertEqual(list(current.get_model('agent_mcp', 'AgentAccessRequest').objects.values()), before_requests)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
