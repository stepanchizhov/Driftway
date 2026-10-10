"""
The scheduled retention run.

    python -m jobs.run_retention

Retention and user-requested erasure are different behaviours and both have to
work. Erasure is something a person asks for and gets immediately; this is the
promise that data nobody asked about does not simply accumulate. The policy has
been written and tested since 14 September; until something actually calls it,
it was a claim rather than a behaviour.

Design notes that matter for a job that deletes things on a timer:

**Safe to run twice.** Selection is by age, and a record already deleted is
simply not selected next time. Two overlapping runs cannot double-delete; the
second finds nothing. So a missed schedule needs no catch-up procedure - the
next ordinary run takes whatever the missed one would have.

**Bounded.** Each pass takes at most MAX_PER_RUN records of each kind. A
backlog is drained across runs rather than in one long transaction, and the
run reports when it stopped early so a persistent backlog is visible rather
than silently perpetual.

**Observable without becoming a leak.** It logs counts and ids of meetups, and
never a coordinate, an email address, a token or an account's display name -
a maintenance log that quietly accumulates precise home locations would defeat
the point of deleting them.

**Honest on failure.** A database that cannot be reached is a failed run, not a
quiet success: it exits non-zero so the scheduler shows red, and it records
nothing rather than recording a run that did not happen.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

# Runnable as a script from the backend directory as well as with -m.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("driftway.retention")


def main() -> int:
    from core.db import SessionLocal, init_db, storage_available
    from core.retention import (
        MAX_PER_RUN,
        purge_anonymous_feedback,
        purge_expired_meetups,
        purge_inactive_accounts,
        record_run,
    )

    init_db()
    if not storage_available():
        log.error(
            "retention run aborted: storage is unavailable. Nothing was "
            "deleted. Check DATABASE_URL and that the database still exists."
        )
        return 2

    started = datetime.now(timezone.utc)
    session = SessionLocal()
    try:
        meetups = purge_expired_meetups(session)
        accounts = purge_inactive_accounts(session)
        feedback = purge_anonymous_feedback(session)
    except Exception:  # noqa: BLE001 - a failed purge must not look like a clean one
        session.rollback()
        log.exception("retention run failed; nothing further was deleted")
        return 1
    finally:
        pass

    capped = (len(meetups) >= MAX_PER_RUN or len(accounts) >= MAX_PER_RUN
              or feedback >= MAX_PER_RUN)
    try:
        record_run(
            session,
            meetups_purged=len(meetups),
            accounts_purged=len(accounts),
            capped=capped,
        )
    finally:
        session.close()

    took = (datetime.now(timezone.utc) - started).total_seconds()
    log.info(
        "retention run complete: meetups=%d accounts=%d capped=%s in %.1fs",
        len(meetups), len(accounts), capped, took,
    )
    if capped:
        log.warning(
            "retention hit the per-run cap of %d; a backlog remains and the "
            "next run will continue it. If this repeats, the schedule is too "
            "infrequent for the volume.",
            MAX_PER_RUN,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
