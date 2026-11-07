from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase

from agent_mcp.access import submit_agent_request, withdraw_agent_request, decide_agent_request, can_use_agent
from agent_mcp.access import revoke_agent_qualification
from agent_mcp.models import AgentQualification


class ModuleRequestStateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='states-user', email='states@example.test', password='local', is_active=True)
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='padif', codename='use_padif'))
        self.reviewer = get_user_model().objects.create_superuser(username='states-reviewer', email='states-reviewer@example.test', password='local')

    def test_withdrawal_is_terminal_and_allows_a_new_request(self):
        item = submit_agent_request(self.user, 'Writing assistance', module_key='padif')
        withdraw_agent_request(item.pk, self.user)
        item.refresh_from_db()
        self.assertEqual(item.status, 'withdrawn')
        self.assertFalse(can_use_agent(self.user))
        with self.assertRaises(ValidationError):
            decide_agent_request(item.pk, self.reviewer, True, 'Too late')
        replacement = submit_agent_request(self.user, 'New purpose', module_key='padif')
        self.assertNotEqual(replacement.pk, item.pk)

    def test_revocation_and_reapproval_create_new_cycles_without_rewriting_history(self):
        item = submit_agent_request(self.user, 'Writing')
        decide_agent_request(item.pk, self.reviewer, True, 'Approved')
        first = AgentQualification.objects.get(user=self.user, module_key='padif').revision
        revoke_agent_qualification(self.user.pk, self.reviewer, 'Revoked')
        grant = AgentQualification.objects.get(user=self.user, module_key='padif')
        self.assertFalse(grant.is_active)
        self.assertIsNotNone(grant.revoked_at)
        self.assertGreater(grant.revision, first)
        again = submit_agent_request(self.user, 'Reapply')
        decide_agent_request(again.pk, self.reviewer, True, 'Approved again')
        grant.refresh_from_db()
        self.assertGreater(grant.revision, first + 1)
        item.refresh_from_db()
        self.assertEqual(item.status, 'approved')
        self.assertEqual(item.decision_note, 'Approved')

    def test_unsupported_module_cannot_create_requests(self):
        for reason, module in [('Use agent', 'other'), ('Use agent', '1')]:
            with self.assertRaises(ValidationError):
                submit_agent_request(self.user, reason, module_key=module)
        self.assertFalse(can_use_agent(self.reviewer, module_key='other'))

    def test_pending_request_stays_invalid_after_padif_permission_is_restored(self):
        item = submit_agent_request(self.user, 'Writing')
        self.user.user_permissions.clear()
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='padif', codename='use_padif'))
        item.refresh_from_db()
        self.assertEqual(item.status, 'invalidated')
        with self.assertRaises(ValidationError):
            decide_agent_request(item.pk, self.reviewer, True, 'Cannot revive')
