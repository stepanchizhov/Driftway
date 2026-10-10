"""
Retention, export and erasure.

Two owner decisions shape this module, and both simplify it considerably.

**A meetup is only needed until it happens.** Plans are not archives. Once the
date has passed there is nothing to preserve, so meetup data is purged on a
schedule rather than kept indefinitely. That also removes the ugliest case in
erasure: with nothing kept long-term, deleting a participant is not rewriting
somebody's future plan, it is tidying a past one.

**Records that cannot be attributed.** A favourite or a meetup created before
anyone signed in carries a random device id, not an identity. Nothing here
guesses whose it is: not from an email address, not from a starting point, not
from the fact that the same browser later signed in - a browser can be shared,
and attributing one parent's origins to another parent's account is exactly the
harm this module exists to avoid. Such records are reachable only by whoever
holds the device id, are excluded from export and erasure, and are removed by
the meetup purges below on the same schedule as everything else. Device
favourites have no expiry of their own and persist until claimed or deleted.

**An inactive account survives one year.** Long enough that a parent returning
after a quiet winter still finds their things; short enough that we are not
holding identity for people who left. After that they can sign up again.

The distinction that decides what goes in an export: properly anonymous data
falls outside data-protection law entirely, but pseudonymous data does not.
A coarsened origin is NOT anonymous while the exact one and the account link
still exist beside it — so exact origins are exported to their owner and
deleted with them. Only genuinely unlinked aggregates are out of scope, and
this module produces none.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

log = logging.getLogger("driftway")

from sqlalchemy import DateTime, Integer, Boolean, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .accounts import BetaAccessInvite, StagingSession, UserAccount
from .db import AppFeedback, Base, Favourite, Feedback, _uuid
from .meetups import (
    MeetupParticipant,
    MeetupSession,
    MeetupVenueCandidate,
    MeetupVote,
)

# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------

#: How long an account survives with no activity. Owner decision, 14 Sep 2026.
INACTIVE_ACCOUNT_RETENTION_DAYS = 365

#: How long a meetup is kept after it happens. A plan has no value afterwards,
#: and a short grace period lets people look back at where they went.
MEETUP_RETENTION_DAYS_AFTER_EVENT = 30

#: For a meetup with no scheduled date, measure from creation instead.
MEETUP_RETENTION_DAYS_UNSCHEDULED = 60


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RetentionRun(Base):
    """One completed scheduled run.

    Exists so "is retention actually running?" has an answer that does not
    depend on reading a scheduler's log. The API reports the most recent row on
    /api/health, which is what turns a configured cron into a verified one.

    Counts only. A row here must never carry an origin, an email address or a
    token: a table recording what was deleted, in detail, would preserve
    exactly what the deletion was for.
    """

    __tablename__ = "retention_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ran_at: Mapped[datetime] = mapped_column(DateTime, default=_now_naive)
    meetups_purged: Mapped[int] = mapped_column(Integer, default=0)
    accounts_purged: Mapped[int] = mapped_column(Integer, default=0)
    #: True when the run stopped at MAX_PER_RUN, so a backlog remains.
    capped: Mapped[bool] = mapped_column(Boolean, default=False)


def record_run(
    session: Session, *, meetups_purged: int, accounts_purged: int, capped: bool
) -> None:
    session.add(RetentionRun(
        meetups_purged=meetups_purged,
        accounts_purged=accounts_purged,
        capped=capped,
    ))
    session.commit()


def last_run(session: Session):
    """The most recent completed run, or None if it has never run here."""
    return session.execute(
        select(RetentionRun).order_by(RetentionRun.ran_at.desc()).limit(1)
    ).scalars().first()


# --------------------------------------------------------------------------
# Export  (right of access)
# --------------------------------------------------------------------------

def export_account(session: Session, user_id: str) -> Dict:
    """Everything held about one person, in a machine-readable shape.

    Exact origins are included. They are this person's own data, and withholding
    them on the grounds that they are sensitive would invert the point of the
    right: the sensitivity is exactly why someone is entitled to see what is
    stored.

    Other participants' details are not included. Their origins are not this
    requester's data to receive.
    """
    account = session.get(UserAccount, user_id)
    if account is None:
        raise LookupError("No such account.")

    participations = session.execute(
        select(MeetupParticipant).where(MeetupParticipant.user_id == user_id)
    ).scalars().all()
    participant_ids = [p.id for p in participations]

    votes = []
    if participant_ids:
        votes = session.execute(
            select(MeetupVote).where(MeetupVote.participant_id.in_(participant_ids))
        ).scalars().all()

    invites = session.execute(
        select(BetaAccessInvite).where(
            BetaAccessInvite.accepted_by_user_id == user_id
        )
    ).scalars().all()

    favourites = session.execute(
        select(Favourite).where(Favourite.owner == user_id)
    ).scalars().all()

    feedback = session.execute(
        select(Feedback).where(Feedback.owner == user_id)
    ).scalars().all()

    app_feedback = session.execute(
        select(AppFeedback).where(AppFeedback.owner == user_id)
    ).scalars().all()

    return {
        "exported_at": _now_naive().isoformat(),
        "account": {
            "id": account.id,
            "display_name": account.display_name,
            "email": account.email,
            "status": account.status,
            "created_at": account.created_at.isoformat(),
            "last_active_at": (account.last_active_at.isoformat()
                               if account.last_active_at else None),
            "auth_provider": account.auth_provider,
            "plan_key": account.plan_key,
            "default_hide_exact_origin": account.default_hide_exact_origin,
        },
        "meetup_participation": [
            {
                "meetup_id": p.meetup_id,
                "display_name": p.display_name,
                # Yours, so you get it.
                "exact_start": {"lat": p.start_lat, "lng": p.start_lng},
                "shown_to_others_as": (
                    {"lat": p.display_lat, "lng": p.display_lng}
                    if p.hide_exact_origin else
                    {"lat": p.start_lat, "lng": p.start_lng}
                ),
                "hid_exact_origin": p.hide_exact_origin,
                "preferred_minutes": p.preferred_minutes,
                "max_minutes": p.max_minutes,
                "joined_at": p.created_at.isoformat(),
            }
            for p in participations
        ],
        "votes": [
            {
                "meetup_id": v.meetup_id,
                "venue_candidate_id": v.venue_candidate_id,
                "value": v.value,
                "comment": v.comment,
                "at": v.updated_at.isoformat(),
            }
            for v in votes
        ],
        "beta_invites_redeemed": [
            {"id": i.id, "accepted_at": i.accepted_at.isoformat()
             if i.accepted_at else None}
            for i in invites
        ],
        "favourites": [
            {
                "label": f.label,
                "place_label": f.place_label,
                "duration_minutes": f.duration_minutes,
                "distance_km": f.distance_km,
                "created_at": f.created_at.isoformat(),
            }
            for f in favourites
        ],
        "route_feedback": [
            {
                "route_id": f.route_id,
                "predicted_minutes": f.predicted_minutes,
                "actual_minutes": f.actual_minutes,
                "would_use_again": f.would_use_again,
                "notes": f.notes,
                "at": f.created_at.isoformat(),
            }
            for f in feedback
        ],
        "app_feedback": [
            {
                "context": f.context,
                "message": f.message,
                "app_version": f.app_version,
                "at": f.created_at.isoformat(),
            }
            for f in app_feedback
        ],
        "not_included": [
            "Other participants' starting points and details, which are theirs "
            "rather than yours.",
            "Anything saved on a device before you signed in. Those records "
            "carry a random per-device id and no identity, so we cannot tell "
            "whose they are - and on a shared browser they may not be yours. "
            "You can move them onto this account yourself from Saved places; "
            "until you do, they stay outside this export and outside erasure.",
        ],
    }


# --------------------------------------------------------------------------
# Erasure  (right to be forgotten)
# --------------------------------------------------------------------------

def erase_account(session: Session, user_id: str) -> Dict[str, int]:
    """Delete a person and everything linked to them.

    A hard delete, per the owner decision that plans are only needed until the
    meetup happens. There is no long-lived archive to protect, so nothing is
    served by keeping a tombstone. If a parent leaves before a meetup, the
    others can arrange it between themselves; the app is not the only way they
    can talk.

    Meetups this person *organised* go too. An organiser's meetup contains
    their origin, and a plan with no owner is not worth the personal data it
    would cost to keep.
    """
    account = session.get(UserAccount, user_id)
    if account is None:
        raise LookupError("No such account.")

    removed = {"participations": 0, "votes": 0, "meetups_organised": 0,
               "favourites": 0, "feedback": 0, "app_feedback": 0, "sessions": 0}

    participations = session.execute(
        select(MeetupParticipant).where(MeetupParticipant.user_id == user_id)
    ).scalars().all()

    for participant in participations:
        for vote in session.execute(
            select(MeetupVote).where(MeetupVote.participant_id == participant.id)
        ).scalars():
            session.delete(vote)
            removed["votes"] += 1

        # A venue they suggested loses its attribution but stays: the other
        # parent may still be considering it, and a place name is not personal
        # data.
        for candidate in session.execute(
            select(MeetupVenueCandidate).where(
                MeetupVenueCandidate.added_by_participant_id == participant.id
            )
        ).scalars():
            candidate.added_by_participant_id = None

        meetup = session.get(MeetupSession, participant.meetup_id)
        if meetup is not None and meetup.owner_participant_id == participant.id:
            removed["meetups_organised"] += _delete_meetup(session, meetup)

        session.delete(participant)
        removed["participations"] += 1

    for fav in session.execute(
        select(Favourite).where(Favourite.owner == user_id)
    ).scalars():
        session.delete(fav)
        removed["favourites"] += 1

    for fb in session.execute(
        select(Feedback).where(Feedback.owner == user_id)
    ).scalars():
        session.delete(fb)
        removed["feedback"] += 1

    for afb in session.execute(
        select(AppFeedback).where(AppFeedback.owner == user_id)
    ).scalars():
        session.delete(afb)
        removed["app_feedback"] += 1

    for sess in session.execute(
        select(StagingSession).where(StagingSession.user_id == user_id)
    ).scalars():
        session.delete(sess)
        removed["sessions"] += 1

    # The invite is kept, with its link to the person cut. It is the founder's
    # record that an invitation was issued and used; it no longer says by whom.
    for invite in session.execute(
        select(BetaAccessInvite).where(
            BetaAccessInvite.accepted_by_user_id == user_id
        )
    ).scalars():
        invite.accepted_by_user_id = None
        invite.bound_email = None

    session.delete(account)
    session.commit()
    log.info("account erased: %s removed=%s", user_id, removed)
    return removed


def _delete_meetup(session: Session, meetup: MeetupSession) -> int:
    """Remove a meetup and everything hanging off it."""
    for vote in session.execute(
        select(MeetupVote).where(MeetupVote.meetup_id == meetup.id)
    ).scalars():
        session.delete(vote)
    for candidate in session.execute(
        select(MeetupVenueCandidate).where(
            MeetupVenueCandidate.meetup_id == meetup.id
        )
    ).scalars():
        session.delete(candidate)
    for participant in session.execute(
        select(MeetupParticipant).where(MeetupParticipant.meetup_id == meetup.id)
    ).scalars():
        session.delete(participant)
    session.delete(meetup)
    return 1


# --------------------------------------------------------------------------
# Scheduled purges
# --------------------------------------------------------------------------

#: Most records one scheduled run will touch. Bounded on purpose: an unbounded
#: delete over a table that has grown quietly is how a maintenance job becomes
#: an outage. Whatever is left over is taken by the next run, and the run
#: reports that it stopped early so a persistent backlog is visible.
MAX_PER_RUN = 200


def purge_expired_meetups(
    session: Session, now: datetime = None, *, limit: int = MAX_PER_RUN
) -> List[str]:
    """Delete meetups whose usefulness has passed.

    A plan is needed until the meetup happens, plus a short window to look back
    at where everyone went. Holding two families' starting points beyond that
    buys nothing and costs the exposure of keeping them.
    """
    now = now or _now_naive()
    scheduled_cutoff = now - timedelta(days=MEETUP_RETENTION_DAYS_AFTER_EVENT)
    created_cutoff = now - timedelta(days=MEETUP_RETENTION_DAYS_UNSCHEDULED)

    purged: List[str] = []
    for meetup in session.execute(select(MeetupSession)).scalars().all():
        if len(purged) >= limit:
            break
        expired = (
            meetup.scheduled_at is not None and meetup.scheduled_at < scheduled_cutoff
        ) or (
            meetup.scheduled_at is None and meetup.created_at < created_cutoff
        )
        if expired:
            _delete_meetup(session, meetup)
            purged.append(meetup.id)

    if purged:
        session.commit()
        log.info("purged %d expired meetups", len(purged))
    return purged


def purge_inactive_accounts(
    session: Session, now: datetime = None, *, limit: int = MAX_PER_RUN
) -> List[str]:
    """Erase accounts dormant for longer than the retention period.

    Measured from last activity, not from creation: someone using the app every
    month is active however long ago they joined.
    """
    now = now or _now_naive()
    cutoff = now - timedelta(days=INACTIVE_ACCOUNT_RETENTION_DAYS)

    stale: List[str] = []
    for account in session.execute(select(UserAccount)).scalars().all():
        last = account.last_active_at or account.created_at
        if last < cutoff:
            stale.append(account.id)

    stale = stale[:limit]
    for user_id in stale:
        erase_account(session, user_id)

    if stale:
        log.info("purged %d inactive accounts", len(stale))
    return stale
