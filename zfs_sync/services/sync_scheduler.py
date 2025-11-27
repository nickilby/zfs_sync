"""Background scheduler service for automatic snapshot synchronization."""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.config import get_settings
from zfs_sync.database import get_db
from zfs_sync.database.repositories import SyncGroupRepository
from zfs_sync.logging_config import get_logger
from zfs_sync.services.conflict_resolution import ConflictResolutionService
from zfs_sync.services.sync_coordination import SyncCoordinationService

logger = get_logger(__name__)


class SyncSchedulerService:
    """Background service for automatically scheduling sync operations."""

    def __init__(self):
        """Initialize the sync scheduler service."""
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.settings = get_settings()

    async def start_scheduler(self) -> None:
        """Start the background sync scheduler."""
        if self._running:
            logger.warning("Sync scheduler is already running")
            return

        if not self.settings.auto_sync_enabled:
            logger.info("Automatic sync is disabled in configuration")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Sync scheduler started")

    async def stop_scheduler(self) -> None:
        """Stop the background sync scheduler."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Sync scheduler stopped")

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop that runs periodically."""
        check_interval = self.settings.sync_check_interval_seconds

        while self._running:
            try:
                await self._process_all_sync_groups()
            except Exception as e:
                logger.error(f"Error in sync scheduler loop: {e}", exc_info=True)

            # Wait for next check interval
            try:
                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                break

    async def _process_all_sync_groups(self) -> None:
        """Process all enabled sync groups."""
        # Create a new database session for this operation
        db = next(get_db())
        try:
            sync_group_repo = SyncGroupRepository(db)
            enabled_groups = sync_group_repo.get_enabled()

            logger.debug(f"Processing {len(enabled_groups)} enabled sync groups")

            for sync_group in enabled_groups:
                if not self._running:
                    break

                if self.should_process_sync_group(sync_group.id, db):
                    try:
                        await self._process_sync_group(sync_group.id, db)
                    except Exception as e:
                        logger.error(
                            f"Error processing sync group {sync_group.id}: {e}",
                            exc_info=True,
                        )
        finally:
            db.close()

    def should_process_sync_group(self, sync_group_id: UUID, db: Session) -> bool:
        """
        Check if a sync group should be processed.

        Returns True if the sync group should be processed now.
        """
        sync_group_repo = SyncGroupRepository(db)
        sync_group = sync_group_repo.get(sync_group_id)

        if not sync_group:
            return False

        if not sync_group.enabled:
            return False

        # Check if sync group has at least 2 systems
        system_ids = [assoc.system_id for assoc in sync_group.system_associations]
        if len(system_ids) < 2:
            logger.debug(f"Sync group {sync_group_id} has less than 2 systems, skipping")
            return False

        # Check if it's time to process based on sync_interval_seconds
        # For now, process every time (can be enhanced with last_processed tracking)
        return True

    async def _process_sync_group(self, sync_group_id: UUID, db: Session) -> None:
        """
        Process a single sync group.

        This includes:
        - Detecting conflicts and logging them
        - Detecting mismatches
        - Generating sync instructions (incremental only)
        - Updating sync states
        """
        logger.info(f"Processing sync group {sync_group_id}")

        try:
            # Detect and log conflicts
            conflict_service = ConflictResolutionService(db)
            sync_group_repo = SyncGroupRepository(db)
            sync_group = sync_group_repo.get(sync_group_id)

            if not sync_group:
                logger.warning(f"Sync group {sync_group_id} not found")
                return

            # Get all datasets for this sync group
            system_ids = [assoc.system_id for assoc in sync_group.system_associations]
            sync_coord_service = SyncCoordinationService(db)
            datasets = sync_coord_service._get_datasets_for_systems(system_ids)

            # Detect conflicts for each dataset and log them
            for pool, dataset in datasets:
                try:
                    conflicts = conflict_service.detect_conflicts(
                        sync_group_id=sync_group_id, pool=pool, dataset=dataset
                    )
                    for conflict in conflicts:
                        self._log_conflict(conflict)
                except Exception as e:
                    logger.warning(
                        f"Error detecting conflicts for {pool}/{dataset} in sync group {sync_group_id}: {e}"
                    )

            # Generate sync instructions (incremental only) for all systems in the group
            # This will also update sync states
            if self.settings.incremental_sync_only:
                try:
                    # Process for all systems in the sync group (system_id=None means all)
                    sync_coord_service.generate_dataset_sync_instructions(
                        sync_group_id=sync_group_id, system_id=None, incremental_only=True
                    )
                except Exception as e:
                    logger.error(
                        f"Error generating sync instructions for sync group {sync_group_id}: {e}",
                        exc_info=True,
                    )
            else:
                logger.warning("incremental_sync_only is False - full syncs not yet implemented")

        except Exception as e:
            logger.error(f"Error processing sync group {sync_group_id}: {e}", exc_info=True)

    def _log_conflict(self, conflict: dict) -> None:
        """
        Log a conflict to the log file.

        Format: [CONFLICT] type={type} sync_group={id} pool={pool} dataset={dataset} snapshot={name} systems={ids} severity={severity}
        """
        conflict_type = conflict.get("type", "unknown")
        sync_group_id = conflict.get("sync_group_id", "unknown")
        pool = conflict.get("pool", "unknown")
        dataset = conflict.get("dataset", "unknown")
        snapshot_name = conflict.get("snapshot_name", "unknown")
        systems = conflict.get("systems", {})
        system_ids = list(systems.keys()) if isinstance(systems, dict) else []
        severity = conflict.get("severity", "unknown")

        logger.warning(
            f"[CONFLICT] type={conflict_type} sync_group={sync_group_id} pool={pool} "
            f"dataset={dataset} snapshot={snapshot_name} systems={system_ids} severity={severity}"
        )
