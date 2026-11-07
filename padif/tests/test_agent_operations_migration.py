"""Historical boolean AI+ conversion preserves data and explicit authority."""
from importlib import import_module
import hashlib
import json
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

class OperationMigrationTests(TransactionTestCase):
    old = ('padif', '0007_documentagentgrant_revision_and_more')
    new = ('padif', '0008_documentagentgrant_allowed_operations_and_more')

    def snapshot(self, apps):
        rows = {name: list(apps.get_model('padif', name).objects.order_by('pk').values())
            for name in ['Document', 'Branch', 'Version', 'Annotation', 'AnnotationReply', 'DocumentCollaborator']}
        return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()

    def test_legacy_sets_requests_and_content_preserved(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.old])
        apps = executor.loader.project_state([self.old]).apps
        try:
            owner = get_user_model().objects.create_superuser(username='migration-owner', email='migration@example.test', password='unused')
            # Persisted legal role, even when account temporarily disabled, must retain old grant.
            viewer = get_user_model().objects.create_user(username='migration-viewer', email='viewer@example.test', password='unused', is_active=False)
            writer = get_user_model().objects.create_user(username='migration-writer', email='writer@example.test', password='unused')
            doc = apps.get_model('padif', 'Document').objects.create(title='Historical private', created_by_id=owner.pk)
            Member = apps.get_model('padif', 'DocumentCollaborator')
            for user, role in [(viewer, 'viewer'), (writer, 'collaborator')]:
                Member.objects.create(document_id=doc.pk, user_id=user.pk, granted_by_id=owner.pk, role=role)
            Grant = apps.get_model('padif', 'DocumentAgentGrant')
            for user in [owner, viewer, writer]:
                Grant.objects.create(document_id=doc.pk, user_id=user.pk, granted_by_id=owner.pk, is_enabled=True, revision=9)
            inactive_doc = apps.get_model('padif', 'Document').objects.create(title='Revoked', created_by_id=owner.pk)
            Grant.objects.create(document_id=inactive_doc.pk, user_id=owner.pk, granted_by_id=owner.pk, is_enabled=False, revoked_at=timezone.now())
            branch = apps.get_model('padif', 'Branch').objects.create(document_id=doc.pk, name='main', is_default=True, created_by_id=owner.pk)
            version = apps.get_model('padif', 'Version').objects.create(document_id=doc.pk, branch_id=branch.pk, created_by_id=owner.pk,
                content='# Historical\n\nKeep content', semantic_version='1.0.0', commit_message='Initial', version_kind='major')
            note = apps.get_model('padif', 'Annotation').objects.create(version_id=version.pk, author_id=owner.pk, kind='question', body='Keep', start_line=1, end_line=1)
            apps.get_model('padif', 'AnnotationReply').objects.create(annotation_id=note.pk, author_id=owner.pk, body='Keep reply')
            Request = apps.get_model('padif', 'DocumentAgentRequest')
            item = Request.objects.create(document_id=inactive_doc.pk, applicant_id=owner.pk, reason='Old pending', role='owner', role_revision=0, qualification_revision=0)
            stale = Request.objects.create(document_id=inactive_doc.pk, applicant_id=viewer.pk, reason='Stale', role='viewer', role_revision=1, qualification_revision=1)
            terminal = Request.objects.create(document_id=doc.pk, applicant_id=owner.pk, reason='Historical', role='owner', role_revision=0, qualification_revision=0, status='approved')
            before = self.snapshot(apps)
            executor = MigrationExecutor(connection)
            executor.migrate([self.new])
            current = executor.loader.project_state([self.new]).apps
            self.assertEqual(self.snapshot(current), before)
            grants = current.get_model('padif', 'DocumentAgentGrant')
            all_ops = ['padif:read', 'padif:annotate', 'padif:version']
            self.assertEqual(grants.objects.get(document_id=doc.pk, user_id=viewer.pk).allowed_operations, ['padif:read'])
            for user in [owner, writer]:
                grant = grants.objects.get(document_id=doc.pk, user_id=user.pk)
                self.assertEqual(grant.allowed_operations, all_ops)
                self.assertEqual(grant.revision, 9)
                self.assertEqual(grant.operations_source, 'legacy_role_limit')
            self.assertEqual(grants.objects.get(document_id=inactive_doc.pk).allowed_operations, [])
            requests = current.get_model('padif', 'DocumentAgentRequest')
            pending = requests.objects.get(pk=item.pk)
            self.assertEqual(pending.requested_operations, all_ops)
            self.assertEqual(pending.status, 'pending')
            self.assertEqual(requests.objects.get(pk=stale.pk).status, 'invalidated')
            self.assertEqual(requests.objects.get(pk=terminal.pk).operations_source, 'legacy_unknown')
            grants.objects.filter(document_id=doc.pk, user_id=writer.pk).update(allowed_operations=['padif:read'], operations_source='explicit')
            import_module('padif.migrations.0008_documentagentgrant_allowed_operations_and_more').backfill_operations(current, type('Schema', (), {'connection': connection})())
            self.assertEqual(grants.objects.get(document_id=doc.pk, user_id=writer.pk).allowed_operations, ['padif:read'])

        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())

    def test_orphan_active_grant_aborts_without_guessing_or_backfilling(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.old])
        apps = executor.loader.project_state([self.old]).apps
        owner = get_user_model().objects.create_user(username='orphan-owner', email='owner@example.test', password='unused')
        outsider = get_user_model().objects.create_user(username='orphan-user', email='other@example.test', password='unused')
        doc = apps.get_model('padif', 'Document').objects.create(title='Orphan grant', created_by_id=owner.pk)
        grant = apps.get_model('padif', 'DocumentAgentGrant').objects.create(document_id=doc.pk, user_id=outsider.pk, granted_by_id=owner.pk, is_enabled=True)
        try:
            with self.assertRaisesRegex(RuntimeError, 'no legal persisted human role'):
                MigrationExecutor(connection).migrate([self.new])
            self.assertFalse(apps.get_model('padif', 'DocumentCollaborator').objects.exists())
        finally:
            apps.get_model('padif', 'DocumentAgentGrant').objects.filter(pk=grant.pk).delete()
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
