"""Executable H2 security checklist; runtime MFA is intentionally absent.

These skipped tests freeze names and rejection paths before H2a introduces
cryptographic dependencies or persisted devices. Implement each contract and
remove its skip only in the corresponding H2a/H2b change.
"""

from unittest import skip

from django.test import SimpleTestCase


@skip("H2a is design-only: no TOTP device, secret, or recovery code exists yet")
class H2aMfaEnrollmentContractTest(SimpleTestCase):
    def test_seed_is_encrypted_before_any_database_write(self):
        self.fail("Implement with the H2a encrypted-device model")

    def test_pending_binding_expires_and_never_authenticates(self):
        self.fail("Implement with the H2a enrollment service")

    def test_first_valid_totp_activates_device_exactly_once(self):
        self.fail("Implement with the H2a enrollment service")

    def test_recovery_codes_are_hash_only_and_displayed_once(self):
        self.fail("Implement with the H2a recovery-code service")

    def test_recovery_code_concurrent_consumption_succeeds_once(self):
        self.fail("Implement with row locking in H2a")

    def test_reset_requires_password_review_and_increments_auth_version(self):
        self.fail("Implement with the H2a reset service")

    def test_audit_and_errors_never_contain_mfa_secrets_or_codes(self):
        self.fail("Implement with H2a audit sanitization")

    def test_h2a_does_not_change_existing_login_behavior(self):
        self.fail("Implement before exposing the H2a enrollment UI")


@skip("H2b is design-only: login and privileged sessions are unchanged")
class H2bPrivilegedLoginContractTest(SimpleTestCase):
    def test_password_only_does_not_authenticate_mfa_required_user(self):
        self.fail("Implement with the H2b pending challenge")

    def test_challenge_is_bound_to_user_session_nonce_and_target(self):
        self.fail("Implement with the H2b pending challenge")

    def test_new_totp_step_succeeds_but_replay_and_old_steps_fail(self):
        self.fail("Implement with last_accepted_step locking")

    def test_fifth_failure_enters_shared_cooldown(self):
        self.fail("Implement with a cross-worker H2b rate limit")

    def test_privileged_session_expires_after_fifteen_minutes(self):
        self.fail("Implement with H2b step-up middleware")

    def test_device_revocation_or_auth_version_change_invalidates_session(self):
        self.fail("Implement with H2b session validation")

    def test_recovery_code_only_enters_rebinding_state(self):
        self.fail("Implement with the H2b restricted recovery state")

    def test_non_privileged_user_login_and_public_paths_remain_unchanged(self):
        self.fail("Implement with the H2b login integration")
