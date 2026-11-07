from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.http import Http404

from agent_mcp.access import submit_agent_request, decide_agent_request
from padif.collaboration import set_collaboration
from padif.services import create_document_from_upload
from padif.agent_requests import submit_document_requests, decide_document_request, withdraw_document_request, relinquish_document_ai
from padif.models import DocumentAgentGrant
from padif.models import DocumentAgentRequest
from agent_mcp.access import revoke_agent_qualification
from padif.permissions import visible_documents


class ArticleAgentRequestTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser(username='article-owner', email='article-owner@example.test', password='local')
        self.user = get_user_model().objects.create_user(username='article-reader', email='article-reader@example.test', password='local', is_active=True)
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='padif', codename='use_padif'))
        item = submit_agent_request(self.user, 'Read drafts')
        decide_agent_request(item.pk, self.owner, True, 'Approved')
        self.document = create_document_from_upload(user=self.owner, upload=SimpleUploadedFile('request.md', b'Private draft.'), title='Request fixture', commit_message='Initial').document
        set_collaboration(document_id=self.document.pk, actor=self.owner, username=self.user.username, action='role', role='viewer')

    def test_pending_request_grants_nothing_until_owner_approves(self):
        item = submit_document_requests(self.user, [self.document.pk], 'Read and summarize')[0]
        self.assertEqual(item.status, 'pending')
        self.assertFalse(visible_documents(self.user, agent=True).exists())
        approved = decide_document_request(item.pk, self.owner, True, 'Approved read access')
        self.assertEqual(approved.status, 'approved')
        self.assertEqual(list(visible_documents(self.user, agent=True)), [self.document])
        grant = DocumentAgentGrant.objects.get(document=self.document, user=self.user)
        self.assertEqual(grant.source_request_id, approved.pk)
        self.assertEqual(grant.source, 'request')

    def test_role_change_and_restore_cannot_revive_old_request(self):
        item = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        for role in ['collaborator', 'viewer']:
            set_collaboration(document_id=self.document.pk, actor=self.owner, username=self.user.username, action='role', role=role)
        item.refresh_from_db()
        self.assertEqual(item.status, 'invalidated')
        with self.assertRaises(ValidationError):
            decide_document_request(item.pk, self.owner, True, 'Stale approval')
        self.assertFalse(visible_documents(self.user, agent=True).exists())

    def test_withdrawn_and_rejected_requests_are_terminal_but_allow_new_applications(self):
        first = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        withdraw_document_request(first.pk, self.user)
        second = submit_document_requests(self.user, [self.document.pk], 'Read again')[0]
        decide_document_request(second.pk, self.owner, False, 'Not yet')
        for item in [first, second]:
            with self.assertRaises(ValidationError):
                decide_document_request(item.pk, self.owner, True, 'Cannot revive')
        third = submit_document_requests(self.user, [self.document.pk], 'New request')[0]
        self.assertEqual(third.status, 'pending')

    def test_direct_grant_resolves_pending_with_reason_and_retries_are_idempotent(self):
        item = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        with self.assertRaises(ValidationError):
            set_collaboration(document_id=self.document.pk, actor=self.owner, username=self.user.username, action='ai', enabled=True)
        set_collaboration(document_id=self.document.pk, actor=self.owner, username=self.user.username, action='ai', enabled=True, note='Owner approved')
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')
        grant = DocumentAgentGrant.objects.get(user=self.user, document=self.document)
        revision = grant.revision
        set_collaboration(document_id=self.document.pk, actor=self.owner, username=self.user.username, action='ai', enabled=True, note='Retry')
        grant.refresh_from_db()
        self.assertEqual(grant.revision, revision)
        self.assertEqual(grant.source_request_id, item.pk)

    def test_relinquish_requires_note_and_preserves_human_role_and_history(self):
        item = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        decide_document_request(item.pk, self.owner, True, 'Approved')
        with self.assertRaises(ValidationError):
            relinquish_document_ai(self.document.pk, self.user, '')
        relinquish_document_ai(self.document.pk, self.user, 'No longer needed')
        self.assertTrue(visible_documents(self.user).filter(pk=self.document.pk).exists())
        self.assertFalse(visible_documents(self.user, agent=True).exists())
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')
        self.assertTrue(DocumentAgentGrant.objects.get(user=self.user, document=self.document).revoked_at)

    def test_duplicate_batch_entries_are_normalized_and_resubmissions_are_rejected(self):
        items = submit_document_requests(self.user, [self.document.pk, self.document.pk], 'Read')
        self.assertEqual(len(items), 1)
        with self.assertRaises(ValidationError):
            submit_document_requests(self.user, [self.document.pk], 'Duplicate')
        self.assertEqual(DocumentAgentRequest.objects.count(), 1)

    def test_article_deletion_invalidates_request_without_losing_its_audit(self):
        from padif.models import Document
        empty = Document.objects.create(title='Empty draft', created_by=self.owner)
        set_collaboration(document_id=empty.pk, actor=self.owner, username=self.user.username, action='role', role='viewer')
        item = submit_document_requests(self.user, [empty.pk], 'Read when ready')[0]
        empty.delete()
        item.refresh_from_db()
        self.assertEqual(item.status, 'invalidated')
        self.assertIsNone(item.document_id)
        with self.assertRaises(Http404):
            decide_document_request(item.pk, self.owner, True, 'Stale approval')
        self.assertFalse(visible_documents(self.user, agent=True).exists())

    def test_module_revocation_clears_pending_and_reapproval_does_not_restore_it(self):
        item = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        revoke_agent_qualification(self.user.pk, self.owner, 'Revoke PAdif')
        board = submit_agent_request(self.user, 'Reapply')
        decide_agent_request(board.pk, self.owner, True, 'New cycle')
        item.refresh_from_db()
        self.assertEqual(item.status, 'invalidated')
        self.assertFalse(DocumentAgentGrant.objects.filter(user=self.user, is_enabled=True).exists())

    def test_batch_is_atomic_and_each_article_can_be_decided_independently(self):
        other = create_document_from_upload(user=self.owner, upload=SimpleUploadedFile('two.md', b'Other.'), title='Other', commit_message='Initial').document
        with self.assertRaises(Http404):
            submit_document_requests(self.user, [self.document.pk, other.pk], 'Mixed visibility')
        self.assertEqual(DocumentAgentRequest.objects.count(), 0)
        set_collaboration(document_id=other.pk, actor=self.owner, username=self.user.username, action='role', role='viewer')
        items = submit_document_requests(self.user, [self.document.pk, other.pk], 'Two drafts')
        decide_document_request(items[0].pk, self.owner, True, 'Approve first')
        decide_document_request(items[1].pk, self.owner, False, 'Decline second')
        self.assertEqual(list(visible_documents(self.user, agent=True)), [self.document])

    def test_disabled_and_reenabled_account_cannot_resume_a_pending_request(self):
        item = submit_document_requests(self.user, [self.document.pk], 'Read')[0]
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        item.refresh_from_db()
        self.assertEqual(item.status, 'invalidated')
