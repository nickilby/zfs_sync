"""Main entry point for running the application."""

import uvicorn

from zfs_sync.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "zfs_sync.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )

