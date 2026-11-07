from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, close_old_connections, transaction
from django.http import Http404
from django.test import TransactionTestCase

from padif.collaboration import set_collaboration
from padif.models import Document, DocumentCollaborator
from padif.services import create_document_from_upload, create_branch, commit_document_version


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locking required')
class CollaborationConcurrencyTests(TransactionTestCase):
    def test_waiting_write_rechecks_access_after_owner_removes_member(self):
        users = []
        for name in ['lock-owner', 'lock-writer']:
            user = get_user_model().objects.create_user(username=name, email=name+'@example.test', password='local', is_active=True)
            user.user_permissions.add(Permission.objects.get(content_type__app_label='padif', codename='use_padif'))
            users.append(user)
        owner, writer = users
        document = create_document_from_upload(user=owner, upload=SimpleUploadedFile('lock.md', b'Original.'),
            title='Lock fixture', commit_message='Initial').document
        DocumentCollaborator.objects.create(document=document, user=writer, granted_by=owner, role='collaborator')
        branch = create_branch(document_id=document.pk, user=writer, name='rewrite', fork_from_version_id=document.current_version_id)
        entered = Event()

        def write():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=writer.pk)
                entered.set()
                try:
                    commit_document_version(document_id=document.pk, user=actor, branch_id=branch.pk,
                        content='Must not save', commit_message='No', version_kind='patch')
                except Http404:
                    return 'denied'
                return 'saved'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Document.objects.select_for_update().get(pk=document.pk)
                pending = pool.submit(write)
                self.assertTrue(entered.wait(timeout=10))
                with self.assertRaises(TimeoutError):
                    pending.result(timeout=.2)
                set_collaboration(document_id=document.pk, actor=owner,
                    username=writer.username, action='remove')
            self.assertEqual(pending.result(timeout=10), 'denied')
        self.assertEqual(branch.versions.count(), 0)
