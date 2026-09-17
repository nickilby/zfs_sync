"""Background scheduler service for automatic snapshot synchronization."""

import asyncio
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from zfs_sync.config import get_settings
from zfs_sync.database import get_db
from zfs_sync.database.repositories import SyncGroupRepository
from zfs_sync.logging_config import get_logger
from zfs_sync.services.conflict_resolution import ConflictResolutionService
from zfs_sync.services.sync.outcomes import SyncOutcomeService
from zfs_sync.services.sync.planner import SyncPlanner
import contextlib

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
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
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
        """Process all enabled sync groups, off the event loop.

        Everything below is synchronous SQLAlchemy. Running it directly inside
        the scheduler's asyncio task blocked the single-worker API for the
        duration of a scan, so a fleet-sized sweep made the service
        unresponsive -- including its own health check.
        """
        await asyncio.to_thread(self._process_all_sync_groups_blocking)

    def _process_all_sync_groups_blocking(self) -> None:
        """Synchronous body of a scheduler pass."""
        # get_db() is a generator dependency; closing it runs its finally
        # block, which the previous `next(get_db())` call skipped entirely.
        db_context = get_db()
        db = next(db_context)
        try:
            sync_group_repo = SyncGroupRepository(db)
            enabled_groups = sync_group_repo.get_enabled()

            logger.debug(f"Processing {len(enabled_groups)} enabled sync groups")

            for sync_group in enabled_groups:
                if not self._running:
                    break

                if self.should_process_sync_group(sync_group.id, db):
                    try:
                        self._process_sync_group(sync_group.id, db)
                    except Exception as e:
                        logger.error(
                            f"Error processing sync group {sync_group.id}: {e}",
                            exc_info=True,
                        )
        finally:
            db.close()
            with contextlib.suppress(StopIteration):
                next(db_context)

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

    def _process_sync_group(self, sync_group_id: UUID, db: Session) -> None:
        """Process a single sync group: detect conflicts, plan, record state."""
        logger.info(f"Processing sync group {sync_group_id}")

        try:
            # Detect and log conflicts
            conflict_service = ConflictResolutionService(db)
            sync_group_repo = SyncGroupRepository(db)
            sync_group = sync_group_repo.get(sync_group_id)

            if not sync_group:
                logger.warning(f"Sync group {sync_group_id} not found")
                return

            # Get all datasets for this sync group (now returns dataset_name -> [(pool, system_id), ...])
            system_ids = [assoc.system_id for assoc in sync_group.system_associations]
            planner = SyncPlanner(db)
            dataset_mappings = planner.dataset_pools(system_ids)

            # Log which datasets are being evaluated for transparency (Bug 2 fix)
            dataset_names = sorted(dataset_mappings.keys())
            logger.info(
                f"Evaluating {len(dataset_names)} datasets for sync group {sync_group_id}: {dataset_names}"
            )

            # Detect conflicts for each unique dataset name only (not per pool)
            # This prevents duplicate conflict logging when the same dataset exists
            # on different pools across systems (Bug 1 fix)
            # Track logged conflicts to prevent duplicates: (dataset, snapshot_name)
            logged_conflicts: set[tuple[str, str]] = set()

            for dataset_name in dataset_names:
                # Get the first pool associated with this dataset for conflict detection
                # The conflict detection checks across all systems regardless of pool
                pool_systems = dataset_mappings[dataset_name]
                if not pool_systems:
                    continue
                pool, _ = pool_systems[0]

                try:
                    conflicts = conflict_service.detect_conflicts(
                        sync_group_id=sync_group_id, pool=pool, dataset=dataset_name
                    )
                    for conflict in conflicts:
                        # Deduplicate by (dataset, snapshot_name) to avoid logging same conflict multiple times
                        conflict_key = (
                            conflict.get("dataset", ""),
                            conflict.get("snapshot_name", ""),
                        )
                        if conflict_key not in logged_conflicts:
                            logged_conflicts.add(conflict_key)
                            self._log_conflict(conflict)
                except Exception as e:
                    logger.warning(
                        f"Error detecting conflicts for {pool}/{dataset_name} in sync group {sync_group_id}: {e}"
                    )

            # Plan the group and record the standing of every pair.
            #
            # This previously called generate_dataset_sync_instructions and
            # discarded the result, while its docstring claimed it updated
            # sync states. It never did: sync_states was written only by
            # conflict resolution, so the dashboard and the status summary
            # showed conflicts and nothing else.
            try:
                plan = planner.plan_group(sync_group_id)
                if plan.skipped_reason:
                    logger.info(
                        "Sync group %s not planned: %s", sync_group_id, plan.skipped_reason
                    )
                else:
                    recorded = SyncOutcomeService(db).record_planned_states(plan.decisions)
                    logger.info(
                        "Sync group %s: %d pair(s) evaluated, %d require syncing, "
                        "%d state(s) recorded",
                        sync_group_id,
                        len(plan.decisions),
                        len(plan.instructions),
                        recorded,
                    )
            except Exception as e:
                logger.error(
                    f"Error planning sync group {sync_group_id}: {e}",
                    exc_info=True,
                )

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
