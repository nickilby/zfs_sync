"""Consistent error responses.

There was no global exception handler, and route-level coverage was uneven:
`conflicts.py` raised no HTTPException across five routes, while the same
"sync group not found" condition returned 404 on `/analysis` and 500 on
`/mismatches` and `/actions` -- one condition, three behaviours, depending on
which route the caller happened to hit.

Domain errors are mapped once, here. Anything unhandled returns a correlation
id that also appears in the log line, so an operator can find the traceback
without the response leaking internal paths or SQL.
"""

import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from zfs_sync.logging_config import get_logger
from zfs_sync.services.sync.renderer import CommandRenderError
from zfs_sync.services.sync.types import SyncGroupNotFound

logger = get_logger(__name__)


def error_body(
    code: str,
    message: str,
    correlation_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build the error envelope every failure response uses.

    ``detail`` is retained alongside ``message`` because FastAPI's own errors
    use it, and the dashboard and client scripts already read it.
    """
    body: Dict[str, Any] = {"error": {"code": code, "message": message}}
    if correlation_id:
        body["error"]["correlation_id"] = correlation_id
    if extra:
        body["error"].update(extra)
    body["detail"] = message
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the handlers that give every failure a consistent shape."""

    @app.exception_handler(SyncGroupNotFound)
    async def _sync_group_not_found(_request: Request, exc: SyncGroupNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error_body(
                "sync_group_not_found",
                str(exc),
                sync_group_id=str(exc.sync_group_id),
            ),
        )

    @app.exception_handler(CommandRenderError)
    async def _command_render_error(_request: Request, exc: CommandRenderError) -> JSONResponse:
        # The planner should have declined such a pair, so reaching here means
        # an instruction was requested that cannot be expressed as a command.
        logger.warning("Command could not be rendered: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=error_body("command_not_renderable", str(exc)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body(
                "validation_error",
                "Request validation failed",
                errors=[
                    {"loc": list(error.get("loc", [])), "msg": error.get("msg", "")}
                    for error in exc.errors()
                ],
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = uuid.uuid4().hex[:12]
        logger.error(
            "Unhandled error [%s] on %s %s: %s",
            correlation_id,
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )
        # Deliberately no str(exc): several routes used to put it in `detail`,
        # which leaked filesystem paths and SQL fragments to callers.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(
                "internal_error",
                "An unexpected error occurred. Quote the correlation id when reporting it.",
                correlation_id=correlation_id,
            ),
        )


__all__ = ["error_body", "register_exception_handlers"]
