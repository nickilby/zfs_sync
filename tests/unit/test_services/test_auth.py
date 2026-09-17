"""API key issuance and validation.

Keys were stored in plaintext and compared by equality. They are now stored as
a SHA-256 digest -- a digest rather than a password KDF because these are 32
bytes of secrets.token_urlsafe entropy, so there is no dictionary to attack,
and the value is checked on every authenticated request.
"""

import pytest

from zfs_sync.database.repositories import SystemRepository
from zfs_sync.services.auth import AuthService, hash_api_key, keys_match


@pytest.fixture
def system(test_db):
    return SystemRepository(test_db).create(
        hostname="hub1", platform="linux", connectivity_status="online"
    )


class TestHashing:
    def test_the_digest_is_deterministic(self):
        assert hash_api_key("abc") == hash_api_key("abc")

    def test_different_keys_give_different_digests(self):
        assert hash_api_key("abc") != hash_api_key("abd")

    def test_comparison_accepts_a_match(self):
        assert keys_match(hash_api_key("abc"), hash_api_key("abc"))

    def test_comparison_rejects_a_mismatch(self):
        assert not keys_match(hash_api_key("abc"), hash_api_key("xyz"))


class TestIssuingKeys:
    def test_the_plaintext_is_returned_once_and_not_stored(self, test_db, system):
        service = AuthService(test_db)

        api_key = service.create_api_key_for_system(system.id)

        stored = SystemRepository(test_db).get(system.id)
        assert api_key
        assert stored.api_key_hash == hash_api_key(api_key)
        assert stored.api_key_hash != api_key
        assert not hasattr(stored, "api_key"), "the plaintext column is gone"

    def test_a_readable_prefix_is_kept_for_identification(self, test_db, system):
        service = AuthService(test_db)

        api_key = service.create_api_key_for_system(system.id)

        stored = SystemRepository(test_db).get(system.id)
        assert api_key.startswith(stored.api_key_prefix)
        assert len(stored.api_key_prefix) < len(api_key)

    def test_issuing_for_an_unknown_system_fails(self, test_db):
        import uuid

        with pytest.raises(ValueError, match="not found"):
            AuthService(test_db).create_api_key_for_system(uuid.uuid4())


class TestValidation:
    def test_a_valid_key_resolves_to_its_system(self, test_db, system):
        service = AuthService(test_db)
        api_key = service.create_api_key_for_system(system.id)

        assert service.validate_api_key(api_key) == system.id

    def test_an_unknown_key_resolves_to_nothing(self, test_db, system):
        service = AuthService(test_db)
        service.create_api_key_for_system(system.id)

        assert service.validate_api_key("some-other-key") is None

    def test_an_empty_key_resolves_to_nothing(self, test_db):
        assert AuthService(test_db).validate_api_key("") is None

    def test_validation_does_not_write(self, test_db, system):
        """last_seen used to be updated on every authenticated request, putting
        a write in the path of every read for liveness the heartbeat records."""
        service = AuthService(test_db)
        api_key = service.create_api_key_for_system(system.id)
        before = SystemRepository(test_db).get(system.id).last_seen

        service.validate_api_key(api_key)

        assert SystemRepository(test_db).get(system.id).last_seen == before


class TestRotationAndRevocation:
    def test_rotation_invalidates_the_previous_key(self, test_db, system):
        service = AuthService(test_db)
        old_key = service.create_api_key_for_system(system.id)

        new_key = service.rotate_api_key(system.id)

        assert new_key != old_key
        assert service.validate_api_key(new_key) == system.id
        assert service.validate_api_key(old_key) is None

    def test_revocation_leaves_the_system_unable_to_authenticate(self, test_db, system):
        service = AuthService(test_db)
        api_key = service.create_api_key_for_system(system.id)

        service.revoke_api_key(system.id)

        assert service.validate_api_key(api_key) is None
        assert SystemRepository(test_db).get(system.id).api_key_hash is None

    def test_a_revoked_system_does_not_match_an_empty_digest(self, test_db, system):
        """A system with no key must not be matched by anything."""
        service = AuthService(test_db)
        service.create_api_key_for_system(system.id)
        service.revoke_api_key(system.id)

        assert service.validate_api_key("") is None
        assert service.validate_api_key(hash_api_key("")) is None


class TestRegistrationToken:
    def test_registration_is_open_when_no_token_is_configured(self, test_db):
        service = AuthService(test_db)
        service.settings.registration_token = None

        allowed, reason = service.check_registration_token(None)

        assert allowed
        assert "unprotected" in reason

    def test_a_correct_token_is_accepted(self, test_db):
        service = AuthService(test_db)
        service.settings.registration_token = "s3cret"
        try:
            allowed, _ = service.check_registration_token("s3cret")
            assert allowed
        finally:
            service.settings.registration_token = None

    def test_a_wrong_or_missing_token_is_refused(self, test_db):
        service = AuthService(test_db)
        service.settings.registration_token = "s3cret"
        try:
            assert not service.check_registration_token("wrong")[0]
            assert not service.check_registration_token(None)[0]
        finally:
            service.settings.registration_token = None
