"""Migrations must run, reverse, and land on the schema the models expect.

None of this was true before. There was no alembic.ini and no env.py, so every
alembic command failed before reading a revision; two revisions both claimed to
follow 001 with incompatible ids, one naming a down_revision that did not
exist; nothing created the base tables the other revisions add columns to; and
003's downgrade called ``sa.GUID()``, which is not a SQLAlchemy type.

Schema was really produced by ``create_all()``, which never alters an existing
table -- so deployments drifted away from the migrations describing them.
"""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from zfs_sync.database.base import Base

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembic_config(tmp_path):
    """An Alembic config pointed at a scratch SQLite database."""
    db_path = tmp_path / "migrations.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.cmd_opts = type("Opts", (), {"x": [f"db_url=sqlite:///{db_path}"]})()
    return config, db_path


def table_names(db_path) -> set:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        return {t for t in inspect(engine).get_table_names() if t != "alembic_version"}
    finally:
        engine.dispose()


def columns(db_path, table) -> set:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        return {c["name"] for c in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


class TestRevisionChain:
    def test_there_is_exactly_one_head(self):
        """Two revisions both followed 001, so the map was unresolvable."""
        script = ScriptDirectory.from_config(
            Config(str(ROOT / "alembic.ini"))
        )

        heads = script.get_heads()
        assert len(heads) == 1, f"expected a single head, found {heads}"

    def test_every_down_revision_resolves(self):
        """One revision named a down_revision that did not exist."""
        script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
        known = {rev.revision for rev in script.walk_revisions()}

        for revision in script.walk_revisions():
            for parent in revision._all_down_revisions:
                assert parent in known, (
                    f"revision {revision.revision} requires {parent}, which does not exist"
                )

    def test_the_chain_is_linear(self):
        script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))

        for revision in script.walk_revisions():
            assert len(revision._all_down_revisions) <= 1, (
                f"revision {revision.revision} branches"
            )


class TestUpgradeFromEmpty:
    def test_upgrade_head_creates_every_table(self, alembic_config):
        """Migrations 001+ add columns to tables nothing created."""
        config, db_path = alembic_config

        command.upgrade(config, "head")

        assert table_names(db_path) == set(Base.metadata.tables)

    def test_the_result_matches_the_models(self, alembic_config):
        config, db_path = alembic_config
        command.upgrade(config, "head")

        expected_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(expected_engine)
        expected = inspect(expected_engine)

        for table in sorted(table_names(db_path)):
            assert columns(db_path, table) == {
                c["name"] for c in expected.get_columns(table)
            }, f"{table} does not match the model"

    def test_the_final_schema_has_the_columns_the_planner_needs(self, alembic_config):
        """The columns whose absence made every group unplannable."""
        config, db_path = alembic_config
        command.upgrade(config, "head")

        assert {"directional", "hub_system_id"} <= columns(db_path, "sync_groups")
        assert "dataset" in columns(db_path, "sync_states")
        assert "snapshot_id" not in columns(db_path, "sync_states")
        assert "sync_runs" in table_names(db_path)


class TestRoundTrip:
    def test_downgrade_to_base_and_back(self, alembic_config):
        """003's downgrade called sa.GUID(), which does not exist."""
        config, db_path = alembic_config

        command.upgrade(config, "head")
        command.downgrade(config, "base")
        assert table_names(db_path) == set()

        command.upgrade(config, "head")
        assert table_names(db_path) == set(Base.metadata.tables)

    def test_each_revision_steps_forward_and_back(self, alembic_config):
        config, db_path = alembic_config
        script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
        revisions = [rev.revision for rev in reversed(list(script.walk_revisions()))]

        for revision in revisions:
            command.upgrade(config, revision)

        for revision in reversed(revisions[:-1]):
            command.downgrade(config, revision)

        command.upgrade(config, "head")
        assert table_names(db_path) == set(Base.metadata.tables)


class TestRecoveringADriftedDatabase:
    """The real case: a database built by create_all() that never ran a migration.

    Reproduces the shape found in the committed development database --
    sync_groups without the directional columns, sync_states still keyed on
    snapshot_id -- which is the state that made the planner report every group
    as unplannable.
    """

    @staticmethod
    def build_drifted(db_path) -> None:
        """A database as create_all() would have left it at revision 002."""
        connection = sqlite3.connect(db_path)
        connection.executescript(
            """
            CREATE TABLE systems (
                id CHAR(36) PRIMARY KEY, created_at DATETIME, updated_at DATETIME,
                hostname VARCHAR(255), platform VARCHAR(50),
                connectivity_status VARCHAR(20), last_seen DATETIME,
                api_key VARCHAR(255), ssh_hostname VARCHAR(255),
                ssh_user VARCHAR(100), ssh_port INTEGER DEFAULT 22, metadata JSON
            );
            CREATE TABLE snapshots (
                id CHAR(36) PRIMARY KEY, created_at DATETIME, updated_at DATETIME,
                name VARCHAR(255), pool VARCHAR(100), dataset VARCHAR(255),
                timestamp DATETIME, size INTEGER, referenced INTEGER, used INTEGER,
                system_id CHAR(36), metadata JSON
            );
            CREATE TABLE sync_groups (
                id CHAR(36) PRIMARY KEY, created_at DATETIME, updated_at DATETIME,
                name VARCHAR(255), description TEXT, enabled BOOLEAN,
                sync_interval_seconds INTEGER, metadata JSON
            );
            CREATE TABLE sync_group_systems (
                id CHAR(36) PRIMARY KEY, created_at DATETIME, updated_at DATETIME,
                sync_group_id CHAR(36), system_id CHAR(36)
            );
            CREATE TABLE sync_states (
                id CHAR(36) PRIMARY KEY, created_at DATETIME, updated_at DATETIME,
                sync_group_id CHAR(36), snapshot_id CHAR(36) NOT NULL,
                system_id CHAR(36), status VARCHAR(20), last_sync DATETIME,
                last_check DATETIME, error_message TEXT, metadata JSON
            );
            CREATE INDEX ix_sync_states_snapshot_id ON sync_states (snapshot_id);

            INSERT INTO systems (id, hostname, platform, connectivity_status, ssh_hostname)
            VALUES ('11111111-1111-1111-1111-111111111111', 'hub1', 'linux', 'online', 'hub1-san');
            INSERT INTO snapshots (id, name, pool, dataset, timestamp, size, system_id)
            VALUES ('22222222-2222-2222-2222-222222222222', 'hubpool1/DATA1@2025-01-01-000000',
                    'hubpool1', 'DATA1', '2025-01-01 00:00:00', 1024,
                    '11111111-1111-1111-1111-111111111111');
            INSERT INTO sync_groups (id, name, enabled, sync_interval_seconds)
            VALUES ('33333333-3333-3333-3333-333333333333', 'legacy group', 1, 3600);
            """
        )
        connection.commit()
        connection.close()

    def test_stamping_then_upgrading_reaches_head_with_data_intact(self, alembic_config):
        config, db_path = alembic_config
        self.build_drifted(db_path)

        # The database is at 002: it has ssh fields and description, but not
        # the directional columns and not the sync_states rework.
        command.stamp(config, "002")
        command.upgrade(config, "head")

        assert table_names(db_path) == set(Base.metadata.tables)
        assert {"directional", "hub_system_id"} <= columns(db_path, "sync_groups")
        assert "dataset" in columns(db_path, "sync_states")

        connection = sqlite3.connect(db_path)
        try:
            assert next(connection.execute("SELECT COUNT(*) FROM systems"))[0] == 1
            assert next(connection.execute("SELECT COUNT(*) FROM snapshots"))[0] == 1
            assert next(connection.execute("SELECT COUNT(*) FROM sync_groups"))[0] == 1
        finally:
            connection.close()

    def test_directional_defaults_to_a_real_boolean_false(self, alembic_config):
        """A literal "false" server default writes the string 'false' on SQLite.

        Python then reads that non-empty string back as truthy, so every
        pre-existing group would look directional -- with no hub set -- the
        moment the schema was brought up to date.
        """
        config, db_path = alembic_config
        self.build_drifted(db_path)

        command.stamp(config, "002")
        command.upgrade(config, "head")

        connection = sqlite3.connect(db_path)
        try:
            stored = next(connection.execute("SELECT directional FROM sync_groups"))[0]
        finally:
            connection.close()

        assert stored in (0, False), f"directional stored as {stored!r}"
        assert bool(stored) is False


class TestNaturalKeyConstraints:
    """Revision 006 deduplicates, then prevents recurrence."""

    @staticmethod
    def seed_with_duplicates(db_path, copies: int = 3) -> None:
        """A snapshot inventory reported several times over, as clients did."""
        connection = sqlite3.connect(db_path)
        connection.execute(
            "INSERT INTO systems (id, hostname, platform, connectivity_status) "
            "VALUES ('11111111-1111-1111-1111-111111111111', 'hub1', 'linux', 'online')"
        )
        for copy in range(copies):
            for index in range(5):
                connection.execute(
                    "INSERT INTO snapshots "
                    "(id, created_at, updated_at, name, pool, dataset, timestamp, size, system_id) "
                    "VALUES (?, datetime('now', ?), datetime('now'), ?, 'hubpool1', 'DATA1', "
                    "'2025-01-01 00:00:00', 1024, '11111111-1111-1111-1111-111111111111')",
                    (
                        f"{copy}-{index}",
                        f"+{copy} seconds",
                        f"hubpool1/DATA1@2025-01-{index + 1:02d}-000000",
                    ),
                )
        connection.commit()
        connection.close()

    def test_duplicates_are_removed_keeping_one_of_each(self, alembic_config):
        config, db_path = alembic_config
        command.upgrade(config, "005")
        self.seed_with_duplicates(db_path, copies=3)

        connection = sqlite3.connect(db_path)
        before = next(connection.execute("SELECT COUNT(*) FROM snapshots"))[0]
        connection.close()
        assert before == 15

        command.upgrade(config, "006")

        connection = sqlite3.connect(db_path)
        try:
            after = next(connection.execute("SELECT COUNT(*) FROM snapshots"))[0]
            distinct = next(
                connection.execute(
                    "SELECT COUNT(*) FROM "
                    "(SELECT DISTINCT system_id, pool, dataset, name FROM snapshots)"
                )
            )[0]
        finally:
            connection.close()

        assert after == 5, "one row per distinct snapshot"
        assert after == distinct, "no duplicates remain"

    def test_the_newest_copy_is_the_one_kept(self, alembic_config):
        config, db_path = alembic_config
        command.upgrade(config, "005")
        self.seed_with_duplicates(db_path, copies=3)

        command.upgrade(config, "006")

        connection = sqlite3.connect(db_path)
        try:
            kept = {row[0] for row in connection.execute("SELECT id FROM snapshots")}
        finally:
            connection.close()

        # Copies are stamped 0, 1, 2 seconds apart; the last written wins.
        assert all(identifier.startswith("2-") for identifier in kept), kept

    def test_a_duplicate_is_rejected_afterwards(self, alembic_config):
        config, db_path = alembic_config
        command.upgrade(config, "005")
        self.seed_with_duplicates(db_path, copies=1)
        command.upgrade(config, "006")

        connection = sqlite3.connect(db_path)
        try:
            with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
                connection.execute(
                    "INSERT INTO snapshots "
                    "(id, created_at, updated_at, name, pool, dataset, timestamp, system_id) "
                    "VALUES ('dupe', datetime('now'), datetime('now'), "
                    "'hubpool1/DATA1@2025-01-01-000000', 'hubpool1', 'DATA1', "
                    "datetime('now'), '11111111-1111-1111-1111-111111111111')"
                )
        finally:
            connection.close()

    def test_the_same_snapshot_name_on_another_system_is_still_allowed(
        self, alembic_config
    ):
        """Uniqueness is per system, not global -- a hub and its spokes all
        hold the same snapshot names."""
        config, db_path = alembic_config
        command.upgrade(config, "head")

        connection = sqlite3.connect(db_path)
        try:
            for identifier, system in (("a", "sys-a"), ("b", "sys-b")):
                connection.execute(
                    "INSERT INTO systems (id, hostname, platform, connectivity_status) "
                    "VALUES (?, ?, 'linux', 'online')",
                    (system, f"host-{identifier}"),
                )
                connection.execute(
                    "INSERT INTO snapshots "
                    "(id, created_at, updated_at, name, pool, dataset, timestamp, system_id) "
                    "VALUES (?, datetime('now'), datetime('now'), "
                    "'pool/DATA1@2025-01-01-000000', 'pool', 'DATA1', datetime('now'), ?)",
                    (identifier, system),
                )
            connection.commit()
            assert next(connection.execute("SELECT COUNT(*) FROM snapshots"))[0] == 2
        finally:
            connection.close()
