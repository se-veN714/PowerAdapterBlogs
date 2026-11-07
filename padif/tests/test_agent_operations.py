"""v2.2 public grant transitions and permission boundaries."""
from django.test import override_settings
from padif.tests import test_collaboration
from agent_mcp.tools import call_tool
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from padif.tests import test_agent_requests
from padif.agent_requests import adjust_document_operations, decide_document_request, set_document_ai
from padif.models import DocumentAgentGrant
from padif.permissions import require_document
from padif.collaboration import set_collaboration

READ = 'padif:read'
NOTE = 'padif:annotate'
VERSION = 'padif:version'

class OperationTransitionTests(TestCase):
    setUp = test_agent_requests.ArticleAgentRequestTests.setUp
    def test_downgrade_then_upgrade_requires_approval(self):
        set_collaboration(document_id=self.document.pk, actor=self.owner, username=self.user.username, action='role', role='collaborator')
        grant = set_document_ai(self.document.pk, self.owner, self.user, True, 'Direct grant')
        result = adjust_document_operations(self.document.pk, self.user, [READ], grant.revision, 'Read only')
        self.assertIsNone(result)
        require_document(self.user, self.document, agent=True, operation=READ)
        with self.assertRaises(PermissionDenied):
            require_document(self.user, self.document, agent=True, operation=NOTE)
        grant.refresh_from_db()
        item = adjust_document_operations(self.document.pk, self.user, [READ, NOTE], grant.revision, 'Review draft')
        with self.assertRaises(PermissionDenied):
            require_document(self.user, self.document, agent=True, operation=NOTE)
        decide_document_request(item.pk, self.owner, True, 'Approve annotations')
        require_document(self.user, self.document, agent=True, operation=NOTE)
        with self.assertRaises(PermissionDenied):
            require_document(self.user, self.document, agent=True, operation=VERSION)

    def collaborator_grant(self, operations=None):
        set_collaboration(document_id=self.document.pk, actor=self.owner, username=self.user.username, action='role', role='collaborator')
        return set_document_ai(self.document.pk, self.owner, self.user, True, 'Direct grant', operations=operations)

    def test_mixed_replacement_reduces_now_and_rejection_preserves_reduction(self):
        grant = self.collaborator_grant([READ, NOTE])
        item = adjust_document_operations(self.document.pk, self.user, [READ, VERSION], grant.revision, 'Use a revision branch')
        grant.refresh_from_db()
        self.assertEqual(grant.allowed_operations, [READ])
        self.assertEqual(item.basis_operations, [READ])
        self.assertEqual(item.base_grant_revision, grant.revision)
        for operation in [NOTE, VERSION]:
            with self.assertRaises(PermissionDenied):
                require_document(self.user, self.document, agent=True, operation=operation)
        decide_document_request(item.pk, self.owner, False, 'Not yet')
        grant.refresh_from_db()
        self.assertEqual(grant.allowed_operations, [READ])

    def test_downgrade_invalidates_pending_and_cannot_be_undone_by_stale_approval(self):
        grant = self.collaborator_grant([READ, NOTE])
        item = adjust_document_operations(self.document.pk, self.user, [READ, NOTE, VERSION], grant.revision, 'Need version')
        adjust_document_operations(self.document.pk, self.user, [READ], grant.revision, 'No annotation')
        item.refresh_from_db()
        self.assertEqual(item.status, 'invalidated')
        with self.assertRaises(ValidationError):
            decide_document_request(item.pk, self.owner, True, 'Stale')
        grant.refresh_from_db()
        self.assertEqual(grant.allowed_operations, [READ])

    def test_invalid_and_stale_or_conflicting_adjustments_are_atomic(self):
        grant = self.collaborator_grant([READ, NOTE])
        for target, revision, note in [([VERSION], grant.revision, 'Invalid'), ([READ, 'unknown'], grant.revision, 'Invalid'),
            ([READ], grant.revision + 1, 'Stale'), ([READ], grant.revision, '')]:
            with self.assertRaises(ValidationError):
                adjust_document_operations(self.document.pk, self.user, target, revision, note)
            grant.refresh_from_db()
            self.assertEqual(grant.allowed_operations, [READ, NOTE])
        adjust_document_operations(self.document.pk, self.user, [READ, NOTE, VERSION], grant.revision, 'New version')
        with self.assertRaises(ValidationError):
            adjust_document_operations(self.document.pk, self.user, [READ, VERSION], grant.revision, 'Conflicting mixed')
        grant.refresh_from_db()
        self.assertEqual(grant.allowed_operations, [READ, NOTE])

    def test_revoke_to_empty_and_noop_dont_touch_other_access(self):
        grant = self.collaborator_grant()
        revision = grant.revision
        adjust_document_operations(self.document.pk, self.user, [READ, NOTE, VERSION], revision, '')
        grant.refresh_from_db()
        self.assertEqual(grant.revision, revision)
        adjust_document_operations(self.document.pk, self.user, [], revision, 'Finished')
        grant.refresh_from_db()
        self.assertFalse(grant.is_enabled)
        self.assertEqual(grant.allowed_operations, [])
        self.assertEqual(require_document(self.user, self.document, write=True), 'collaborator')

    def test_viewer_cannot_request_write_and_first_request_defaults_read(self):
        from padif.agent_requests import submit_document_requests
        item = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        self.assertEqual(item.requested_operations, [READ])
        with self.assertRaises(ValidationError):
            adjust_document_operations(self.document.pk, self.user, [READ, NOTE], 0, 'Write')
        with self.assertRaises(ValidationError):
            set_document_ai(self.document.pk, self.owner, self.user, True, 'Grant different', operations=[READ, VERSION])

    def test_direct_grant_cannot_silently_approve_a_different_pending_target(self):
        from padif.agent_requests import submit_document_requests
        set_collaboration(document_id=self.document.pk, actor=self.owner, username=self.user.username, action='role', role='collaborator')
        item = submit_document_requests(self.user, [self.document.pk], 'Only read')[0]
        with self.assertRaises(ValidationError):
            set_document_ai(self.document.pk, self.owner, self.user, True, 'Different target')
        item.refresh_from_db()
        self.assertEqual(item.status, 'pending')
        set_document_ai(self.document.pk, self.owner, self.user, True, 'Exact target', operations=[READ])
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')


@override_settings(MFA_ENFORCEMENT_ENABLED=False, PUBLIC_SITE_URL='https://testserver')
class OperationGatewayTests(TestCase):
    setUp = test_collaboration.DocumentCollaborationTests.setUp
    user = test_collaboration.DocumentCollaborationTests.user
    make_document = test_collaboration.DocumentCollaborationTests.make_document
    change = test_collaboration.DocumentCollaborationTests.change
    connection = test_collaboration.DocumentCollaborationTests.connection
    token = test_collaboration.DocumentCollaborationTests.token

    def test_annotation_grant_does_not_allow_version_tool_or_old_api(self):
        self.change(self.writer, 'ai', enabled=True, operations=[READ, NOTE])
        connection = self.connection(self.writer)
        result = call_tool(connection, 'create_branch', {'document_id': self.document.pk, 'name': 'denied', 'fork_from_version_id': self.head.pk, 'request_id': 'scope-split'})
        self.assertEqual(result.get('error'), 'DOCUMENT_PERMISSION_DENIED')
        reply = call_tool(connection, 'reply_annotation', {'annotation_id': self.annotation.pk, 'body': 'Allowed', 'request_id': 'note-ok'})
        self.assertNotIn('error', reply)
        response = self.client.post('/padif/api/documents/%s/branches/' % self.document.pk,
            json.dumps({'name': 'denied-api', 'fork_from_version_id': self.head.pk}), content_type='application/json', **self.token(self.writer))
        self.assertEqual(response.status_code, 403)
        grant = DocumentAgentGrant.objects.get(document=self.document, user=self.writer)
        adjust_document_operations(self.document.pk, self.writer, [READ], grant.revision, 'Stop annotation')
        self.assertEqual(call_tool(connection, 'reply_annotation', {'annotation_id': self.annotation.pk, 'body': 'Allowed', 'request_id': 'note-ok'}).get('error'), 'DOCUMENT_PERMISSION_DENIED')

    def test_version_only_article_grant_and_scope_intersection_are_independent(self):
        self.change(self.writer, 'ai', enabled=True, operations=[READ, VERSION])
        connection = self.connection(self.writer)
        denied = call_tool(connection, 'reply_annotation', {'annotation_id': self.annotation.pk, 'body': 'Denied', 'request_id': 'no-note'})
        self.assertEqual(denied.get('error'), 'DOCUMENT_PERMISSION_DENIED')
        # Legacy write-only OAuth scope is valid; article read remains a baseline.
        connection.scopes = [VERSION]
        connection.save(update_fields=['scopes'])
        created = call_tool(connection, 'create_branch', {'document_id': self.document.pk, 'name': 'version-only', 'fork_from_version_id': self.head.pk, 'request_id': 'version-only'})
        self.assertNotIn('error', created)
        self.assertEqual(call_tool(connection, 'get_version', {'version_id': self.head.pk}).get('error'), 'INSUFFICIENT_SCOPE')

    def test_workspace_exposes_exact_permissions_without_changing_legacy_role_flag(self):
        self.change(self.writer, 'ai', enabled=True, operations=[READ, NOTE])
        connection = self.connection(self.writer)
        connection.scopes = [READ]
        connection.save(update_fields=['scopes'])
        workspace = call_tool(connection, 'get_workspace', {'document_id': self.document.pk})
        permissions = workspace['permissions']
        self.assertEqual(permissions['allowed_operations'], [READ, NOTE])
        self.assertEqual(permissions['effective_operations'], [READ])
        self.assertTrue(permissions['can_write'])  # Historical human role upper bound only.
        self.assertFalse(permissions['can_annotate'])
        self.assertFalse(permissions['can_commit_version'])

    def test_malformed_empty_or_readless_grant_never_falls_back_to_role_permissions(self):
        self.change(self.writer, 'ai', enabled=True)
        connection = self.connection(self.writer)
        for operations in [[], [NOTE]]:
            DocumentAgentGrant.objects.filter(document=self.document, user=self.writer).update(allowed_operations=operations)
            result = call_tool(connection, 'reply_annotation', {'annotation_id': self.annotation.pk, 'body': 'Denied', 'request_id': 'readless'})
            self.assertEqual(result.get('error'), 'DOCUMENT_PERMISSION_DENIED')
