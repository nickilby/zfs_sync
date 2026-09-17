"""Typed database errors.

``BaseRepository`` mapped every ``IntegrityError`` to
``ValueError("constraint violation")``, which discards the one thing a caller
needs: whether the row was a duplicate or referred to something that does not
exist. That is why creating a sync group with an unknown ``system_id``
surfaced as a 500 rather than a 400.
"""

from typing import Optional


class RepositoryError(ValueError):
    """Base class for database errors a caller might reasonably handle.

    Subclasses ``ValueError`` deliberately: several routes already catch that
    and turn it into a 4xx, and widening the type would have silently turned
    those into 500s. New code should catch the specific subclasses.
    """

    def __init__(self, message: str, *, model: Optional[str] = None, detail: str = ""):
        self.model = model
        self.detail = detail
        super().__init__(message)


class DuplicateRecord(RepositoryError):
    """A uniqueness constraint rejected the write. Maps to HTTP 409."""


class InvalidReference(RepositoryError):
    """A foreign key pointed at a row that does not exist. Maps to HTTP 400."""


class ConstraintViolation(RepositoryError):
    """Some other integrity constraint rejected the write. Maps to HTTP 409."""


def classify_integrity_error(
    error: Exception, model: Optional[str] = None
) -> RepositoryError:
    """Turn a driver-specific IntegrityError into something meaningful.

    The wording differs per driver, so this matches on the fragments SQLite
    and PostgreSQL actually emit rather than on an exception class.
    """
    detail = str(getattr(error, "orig", error))
    lowered = detail.lower()

    if "foreign key" in lowered or "violates foreign key constraint" in lowered:
        return InvalidReference(
            f"{model or 'Record'} refers to something that does not exist",
            model=model,
            detail=detail,
        )

    if "unique" in lowered or "duplicate key" in lowered:
        return DuplicateRecord(
            f"{model or 'Record'} already exists", model=model, detail=detail
        )

    return ConstraintViolation(
        f"{model or 'Record'} violates a database constraint", model=model, detail=detail
    )


__all__ = [
    "ConstraintViolation",
    "DuplicateRecord",
    "InvalidReference",
    "RepositoryError",
    "classify_integrity_error",
]
