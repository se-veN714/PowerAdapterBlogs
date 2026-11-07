import hashlib
import json

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class TwoLevelAccessMigrationTests(TransactionTestCase):
    def test_legacy_qualifications_and_explicit_ai_are_preserved_without_fake_applications(self):
        executor = MigrationExecutor(connection)
        old = [('agent_mcp', '0002_agentqualification_agentaccessrequest'), ('padif', '0006_documentagentgrant_documentcollaborator')]
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        try:
            user = get_user_model().objects.create_user(username='v2-legacy', email='v2-legacy@example.test', password='local', is_active=True)
            approved = apps.get_model('agent_mcp', 'AgentAccessRequest').objects.create(applicant_id=user.pk,
                reason='Legacy request', status='approved', reviewed_by_id=user.pk, reviewed_at=timezone.now(), decision_note='Legacy decision')
            qualification = apps.get_model('agent_mcp', 'AgentQualification').objects.create(user_id=user.pk, is_active=True)
            doc = apps.get_model('padif', 'Document').objects.create(created_by_id=user.pk, title='Preserved draft')
            branch = apps.get_model('padif', 'Branch').objects.create(document_id=doc.pk, created_by_id=user.pk, name='main', is_default=True)
            version = apps.get_model('padif', 'Version').objects.create(document_id=doc.pk, branch_id=branch.pk, created_by_id=user.pk,
                content='# Legacy\n\nUnchanged.', commit_message='Initial', semantic_version='1.0.0', version_kind='major')
            doc.current_version_id = version.pk
            doc.save()
            apps.get_model('padif', 'DocumentAgentGrant').objects.create(document_id=doc.pk, user_id=user.pk, granted_by_id=user.pk, is_enabled=True)
            names = ['Document', 'Branch', 'Version', 'Annotation', 'AnnotationReply', 'DocumentCollaborator', 'DocumentAgentGrant']
            fields = {name: [field.attname for field in apps.get_model('padif', name)._meta.fields] for name in names}

            def fingerprint(registry):
                data = {name: list(registry.get_model('padif', name).objects.order_by('pk').values(*fields[name])) for name in names}
                return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

            before = fingerprint(apps)
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
            current = executor.loader.project_state().apps
            self.assertEqual(fingerprint(current), before)
            grant = current.get_model('padif', 'DocumentAgentGrant').objects.get(document_id=doc.pk)
            self.assertTrue(grant.is_enabled)
            self.assertEqual(grant.source, 'legacy')
            self.assertIsNone(grant.source_request_id)
            self.assertEqual(current.get_model('padif', 'DocumentAgentRequest').objects.count(), 0)
            current_q = current.get_model('agent_mcp', 'AgentQualification').objects.get(pk=qualification.pk)
            self.assertEqual(current_q.module_key, 'padif')
            self.assertTrue(current_q.is_active)
            result = current.get_model('agent_mcp', 'AgentAccessRequest').objects.get(pk=approved.pk)
            self.assertEqual(result.decision_note, 'Legacy decision')
            self.assertEqual(result.closed_at, result.reviewed_at)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
