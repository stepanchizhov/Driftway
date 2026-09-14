"""
Schema migrations.

`create_all()` creates tables that are missing. It never alters a table that
already exists, so every column added after a table's first deployment is
silently absent until something queries it and the request fails at runtime.
That has already happened once in this project.

Alembic is the eventual answer. This is deliberately smaller: an explicit,
ordered list of forward-only steps, each idempotent, run at startup after
`create_all()`. It is enough to carry real beta accounts across a schema change
without a manual database session, and it is honest about what it is - a
stepping stone, not a migration framework.

Rules that keep it safe:

  - **Additive only.** No step drops a column, drops a table, or rewrites data
    destructively. A rollback is therefore "deploy the previous code", which
    still reads the older columns fine.
  - **Idempotent.** Every step checks the current schema first, so re-running
    on an already-migrated database is a no-op. Restarts and repeated deploys
    are normal.
  - **Recorded.** Applied steps are written to `schema_migrations`, so the log
    shows what ran and when.
  - **Never fatal.** A failing migration logs loudly and leaves the app
    serving routes and search, exactly as an unreachable database does. A
    schema problem must not become an outage of the core product.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, List, Tuple

from sqlalchemy import DateTime, String, inspect, text
from sqlalchemy.orm import Mapped, mapped_column

log = logging.getLogger("driftway")

from .db import Base, _now, engine


class SchemaMigration(Base):
    """One applied step. Present so a deployed database can say what it has."""

    __tablename__ = "schema_migrations"

    step_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def _columns(table: str) -> set:
    """Column names currently on a table, or empty if it does not exist."""
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _add_column(table: str, column: str, ddl_type: str) -> None:
    """Add a column if it is missing.

    ADD COLUMN is the one schema change SQLite and Postgres both support
    straightforwardly, which is why every step here is expressed as one.
    """
    if not _columns(table):
        # The table does not exist yet; create_all() will build it complete.
        return
    if column in _columns(table):
        return
    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl_type}'))
    log.info("migration: added %s.%s", table, column)


# Ordered, forward-only. Append new steps; never edit or reorder an applied one,
# because a database that already ran it will not run it again.
#
# Each entry is (step_id, callable). The id is recorded in schema_migrations.
STEPS: List[Tuple[str, Callable[[], None]]] = [
    # The column that caused the original "no such column" failure. Present on
    # any database built since, but recorded so an older one is repaired rather
    # than rebuilt.
    ("0001_venue_added_by_participant", lambda: _add_column(
        "meetup_venue_candidates", "added_by_participant_id", "VARCHAR(36)",
    )),
]


def run_migrations() -> List[str]:
    """Apply any outstanding steps. Never raises.

    Returns the ids applied during this call, so startup logging can say
    whether anything changed.
    """
    applied: List[str] = []
    try:
        Base.metadata.tables["schema_migrations"].create(engine, checkfirst=True)
    except Exception as e:  # noqa: BLE001
        log.error("migration bookkeeping unavailable (%s: %s); skipping",
                  type(e).__name__, e)
        return applied

    try:
        with engine.begin() as conn:
            done = {
                r[0] for r in conn.execute(text("SELECT step_id FROM schema_migrations"))
            }
    except Exception as e:  # noqa: BLE001
        log.error("could not read applied migrations (%s: %s); skipping",
                  type(e).__name__, e)
        return applied

    for step_id, step in STEPS:
        if step_id in done:
            continue
        try:
            step()
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO schema_migrations (step_id, applied_at) "
                         "VALUES (:s, :t)"),
                    {"s": step_id, "t": _now()},
                )
            applied.append(step_id)
        except Exception as e:  # noqa: BLE001
            # Loud, but not fatal. Routing and search do not depend on this.
            log.error(
                "migration %s failed (%s: %s). The app will keep serving routes "
                "and search; features needing this column will fail until it is "
                "fixed.",
                step_id, type(e).__name__, e,
            )
            break

    if applied:
        log.info("migrations applied: %s", ", ".join(applied))
    return applied


def pending_steps() -> List[str]:
    """Step ids not yet recorded as applied. For health reporting."""
    try:
        with engine.begin() as conn:
            done = {
                r[0] for r in conn.execute(text("SELECT step_id FROM schema_migrations"))
            }
    except Exception:  # noqa: BLE001
        return [s for s, _ in STEPS]
    return [s for s, _ in STEPS if s not in done]
