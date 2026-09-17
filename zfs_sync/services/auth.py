"""Authentication and API key management.

Keys were stored in plaintext and looked up by equality. Combined with
``SystemResponse`` exposing the column, an unauthenticated ``GET /systems``
returned every key in the fleet.

Keys are now stored as a SHA-256 digest. A digest rather than a password KDF
is the right choice here: these are 32 bytes of ``secrets.token_urlsafe``
entropy, so there is no dictionary to attack, and lookup happens on every
authenticated request -- bcrypt or argon2 would add latency for no benefit.
The digest is deterministic so it can be indexed and looked up directly, and
the comparison is constant-time.
"""

import hashlib
import hmac
import secrets
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.config import get_settings
from zfs_sync.database.repositories import SystemRepository
from zfs_sync.logging_config import get_logger

logger = get_logger(__name__)

#: Shown alongside a system so an operator can tell which key is in use
#: without the key itself appearing anywhere.
KEY_PREFIX_LENGTH = 8


def hash_api_key(api_key: str) -> str:
    """Return the stored form of an API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def keys_match(candidate_hash: str, stored_hash: str) -> bool:
    """Compare two digests without leaking timing information."""
    return hmac.compare_digest(candidate_hash, stored_hash)


class AuthService:
    """Issues and validates system API keys."""

    def __init__(self, db: Session):
        self.db = db
        self.system_repo = SystemRepository(db)
        self.settings = get_settings()

    def generate_api_key(self) -> str:
        """Generate a key. Returned once; only its digest is stored."""
        return secrets.token_urlsafe(self.settings.api_key_length)

    def create_api_key_for_system(self, system_id: UUID) -> str:
        """Issue a key for a system and return the plaintext exactly once."""
        system = self.system_repo.get(system_id)
        if not system:
            raise ValueError(
                f"System '{system_id}' not found. Cannot create an API key for it."
            )

        api_key = self.generate_api_key()
        self.system_repo.update(
            system_id,
            api_key_hash=hash_api_key(api_key),
            api_key_prefix=api_key[:KEY_PREFIX_LENGTH],
        )
        logger.info("Issued API key for system %s", system_id)
        return api_key

    def validate_api_key(self, api_key: str) -> Optional[UUID]:
        """Return the system this key belongs to, or None.

        Deliberately does not touch ``last_seen``. Writing on every
        authenticated request put a write in the path of every read, for
        liveness information the heartbeat endpoint already records.
        """
        if not api_key:
            return None

        candidate = hash_api_key(api_key)
        system = self.system_repo.get_by_api_key_hash(candidate)
        if system is None:
            return None

        # The lookup already matched, but compare explicitly so the code does
        # not depend on the database's comparison semantics.
        if not keys_match(candidate, system.api_key_hash):
            return None
        return system.id

    def revoke_api_key(self, system_id: UUID) -> None:
        """Remove a system's key, leaving it unable to authenticate."""
        system = self.system_repo.get(system_id)
        if not system:
            raise ValueError(f"System '{system_id}' not found. Cannot revoke its API key.")

        self.system_repo.update(system_id, api_key_hash=None, api_key_prefix=None)
        logger.info("Revoked API key for system %s", system_id)

    def rotate_api_key(self, system_id: UUID) -> str:
        """Replace a system's key, returning the new plaintext once."""
        new_key = self.create_api_key_for_system(system_id)
        logger.info("Rotated API key for system %s", system_id)
        return new_key

    def check_registration_token(self, provided: Optional[str]) -> Tuple[bool, str]:
        """Decide whether a registration request may proceed.

        Registration issues a working API key, so leaving it open lets anyone
        who can reach the service mint credentials for it. A token makes that
        an explicit choice rather than the default.

        Returns whether to allow it, and why -- so the caller can log an
        unprotected registration rather than letting it pass silently.
        """
        expected = self.settings.registration_token
        if not expected:
            return True, "registration is unprotected (no registration_token configured)"
        if provided and hmac.compare_digest(provided, expected):
            return True, "registration token accepted"
        return False, "registration token missing or incorrect"


__all__ = ["KEY_PREFIX_LENGTH", "AuthService", "hash_api_key", "keys_match"]
