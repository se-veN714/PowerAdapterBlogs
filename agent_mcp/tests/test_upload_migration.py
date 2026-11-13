"""The additive staging schema must not rewrite old authorization/manuscript rows."""
import hashlib
import json

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings

from agent_mcp.tests import test_mcp


@override_settings(PUBLIC_SITE_URL='https://testserver', MFA_ENFORCEMENT_ENABLED=False)
class UploadMigrationTests(TransactionTestCase):
    def test_additive_schema_preserves_existing_rows(self):
        test_mcp.OAuthMcpTests.setUp(self)
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        old_targets = [node for node in latest if node[0] != 'agent_mcp'] + [('agent_mcp', '0005_agentqualification_managed_by_and_more')]
        executor.migrate(old_targets)

        def fingerprint(apps):
            snapshot = {}
            for app, model in [('padif', name) for name in ['Document', 'Version', 'Annotation', 'AnnotationReply',
                'DocumentCollaborator', 'DocumentAgentGrant', 'DocumentAgentRequest']] + [('agent_mcp', name) for name in ['Connection', 'AgentQualification', 'AgentAccessRequest', 'WriteReceipt']]:
                snapshot[app+'.'+model] = list(apps.get_model(app, model).objects.order_by('pk').values())
            return hashlib.sha256(json.dumps(snapshot, default=str, sort_keys=True).encode()).hexdigest()

        before = fingerprint(executor.loader.project_state(old_targets).apps)
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        after = fingerprint(executor.loader.project_state(latest).apps)
        self.assertEqual(before, after)
        self.assertIn('agent_mcp_markdownuploadchunk', connection.introspection.table_names())
