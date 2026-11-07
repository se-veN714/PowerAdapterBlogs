"""Prove additive ACL migration preserves historical source and discussion rows."""
import hashlib
import json

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CollaborationMigrationTests(TransactionTestCase):
    def test_existing_data_is_unchanged_and_no_access_is_backfilled(self):
        executor = MigrationExecutor(connection)
        old = ('padif', '0005_branching')
        latest = ('padif', '0006_documentagentgrant_documentcollaborator')
        executor.migrate([old])
        apps = executor.loader.project_state([old]).apps
        try:
            owner = get_user_model().objects.create_user(username='legacy-acl-owner', email='legacy-acl@example.test', password='unused', is_active=True)
            document = apps.get_model('padif', 'Document').objects.create(title='Legacy private', created_by_id=owner.pk)
            branch = apps.get_model('padif', 'Branch').objects.create(document_id=document.pk,
                name='main', is_default=True, created_by_id=owner.pk)
            version = apps.get_model('padif', 'Version').objects.create(document_id=document.pk, branch_id=branch.pk,
                content='# Original\n\nAn unchanged paragraph.', semantic_version='1.0.0', commit_message='Old initial',
                version_kind='major', created_by_id=owner.pk)
            document.current_version_id = version.pk
            document.save()
            note = apps.get_model('padif', 'Annotation').objects.create(version_id=version.pk, author_id=owner.pk,
                kind='question', body='Historical question', start_line=3, end_line=3)
            apps.get_model('padif', 'AnnotationReply').objects.create(annotation_id=note.pk,
                author_id=owner.pk, body='Historical reply')

            def snapshot(registry):
                rows = {name: list(registry.get_model('padif', name).objects.order_by('pk').values())
                        for name in ['Document', 'Branch', 'Version', 'Annotation', 'AnnotationReply']}
                return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()

            before = snapshot(apps)
            executor = MigrationExecutor(connection)
            executor.migrate([latest])
            current = executor.loader.project_state([latest]).apps
            self.assertEqual(snapshot(current), before)
            self.assertEqual(current.get_model('padif', 'DocumentCollaborator').objects.count(), 0)
            self.assertEqual(current.get_model('padif', 'DocumentAgentGrant').objects.count(), 0)
        finally:
            restore = MigrationExecutor(connection)
            restore.migrate(restore.loader.graph.leaf_nodes())
