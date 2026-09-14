"""
Meet Halfway endpoints: beta invites, meetup sessions, participants, votes.

Two rules run through every handler here.

**Storage isolation.** These endpoints need persistence and say so with a clear
503 when it is missing. They must never be able to stop the app importing or
take `/api/generate` and `/api/search` down with them - that outage already
happened once and cost two months of deploys.

**Capability separation.** A join token writes for one participant in one
meetup. A results slug reads a redacted projection. An admin token mints beta
invites. No handler accepts one where it means another.
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

log = logging.getLogger("driftway")

from core.identity import (
    IdentityError,
    account_for_identity,
    is_configured as identity_configured,
    link_identity,
    verify_access_token,
)
from core.retention import (
    MAX_PER_RUN,
    erase_account,
    export_account,
    purge_expired_meetups,
    purge_inactive_accounts,
    record_run,
)
from core.current_user import CredentialsRejected, current_account
from core.accounts import (
    disable_account,
    InviteError,
    SESSION_COOKIE,
    UserAccount,
    accept_invite,
    account_for_session,
    close_session,
    create_invite,
    invite_status,
    open_session,
    revoke_invite,
)
from core.accounts import BetaAccessInvite
from core.config import (
    MAX_PARTICIPANTS_PER_MEETUP,
    MAX_VENUE_CANDIDATES,
    SELF_REVEAL_METRES,
    RegistrationMode,
    admin_token,
    meet_halfway_enabled,
    registration_mode,
)
from core.db import get_session, storage_available
from core.meetup_schemas import (
    AcceptInviteRequest,
    AccountPublic,
    AddVenueRequest,
    BetaInvitePublic,
    CreateMeetupRequest,
    JoinMeetupRequest,
    MeetupCreated,
    MeetupPublic,
    VoteRequest,
    meetup_public,
)
from core.meetup_ranking import ParticipantNeed, rank_venues, score_venue
from core.meetups import SqlMeetupRepository, _rough_metres, coarsen
from core.models import Coord
from core.router import get_router

router = APIRouter()


# --------------------------------------------------------------------- gates

def _require_feature() -> None:
    """Meet Halfway is a staging experiment behind a server-side flag."""
    if not meet_halfway_enabled():
        raise HTTPException(status_code=404, detail="Not found.")


def _require_storage() -> None:
    """Distinct from the routing endpoints' storage guard: this one names the
    meetup subsystem so an operator can tell which half is down."""
    if not storage_available():
        raise HTTPException(
            status_code=503,
            detail="meetup_storage_unavailable: sharing and votes are offline. "
                   "Route planning still works.",
        )


def _require_admin(x_admin_token: Optional[str] = Header(None)) -> None:
    """Founder-only. Absent configuration refuses everything rather than
    defaulting to open - a missing secret is not permission."""
    expected = admin_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin access is not configured on this deployment.",
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=403, detail="Not permitted.")


def _repo(session: Session = Depends(get_session)) -> SqlMeetupRepository:
    return SqlMeetupRepository(session)


# ------------------------------------------------------- beta access / admin

@router.post("/admin/beta-invites", response_model=BetaInvitePublic)
def create_beta_invite(
    ttl_days: int = 14,
    bound_email: Optional[str] = None,
    _: None = Depends(_require_admin),
    session: Session = Depends(get_session),
):
    _require_storage()
    row, raw = create_invite(session, ttl_days=ttl_days, bound_email=bound_email)
    # The only response that ever carries the raw token.
    return BetaInvitePublic(
        id=row.id,
        status=invite_status(row),
        created_at=row.created_at.isoformat(),
        expires_at=row.expires_at.isoformat(),
        bound_email=row.bound_email,
        invite_token=raw,
    )


@router.get("/admin/beta-invites", response_model=list[BetaInvitePublic])
def list_beta_invites(
    _: None = Depends(_require_admin),
    session: Session = Depends(get_session),
):
    _require_storage()
    rows = session.query(BetaAccessInvite).order_by(
        BetaAccessInvite.created_at.desc()
    ).all()
    # No raw tokens here - they exist only at creation time.
    return [
        BetaInvitePublic(
            id=r.id,
            status=invite_status(r),
            created_at=r.created_at.isoformat(),
            expires_at=r.expires_at.isoformat(),
            bound_email=r.bound_email,
        )
        for r in rows
    ]


@router.post("/admin/beta-invites/{invite_id}/revoke")
def revoke_beta_invite(
    invite_id: str,
    _: None = Depends(_require_admin),
    session: Session = Depends(get_session),
):
    _require_storage()
    if not revoke_invite(session, invite_id):
        raise HTTPException(
            status_code=409,
            detail="That invite cannot be revoked (already used, or already revoked).",
        )
    return {"ok": True}


@router.post("/admin/retention/run")
def run_retention_now(
    _: None = Depends(_require_admin),
    session: Session = Depends(get_session),
):
    """Run the scheduled purge now.

    The same work `python -m jobs.run_retention` does, reachable over HTTP so
    the schedule can come from anywhere that can make an authenticated request
    - including a free external scheduler - rather than requiring a Render Cron
    service. Safe to call repeatedly: selection is by age, so a second call
    finds nothing left to take.

    Returns counts only. Never the ids of accounts, never an origin.
    """
    _require_storage()
    meetups = purge_expired_meetups(session)
    accounts = purge_inactive_accounts(session)
    capped = len(meetups) >= MAX_PER_RUN or len(accounts) >= MAX_PER_RUN
    record_run(
        session,
        meetups_purged=len(meetups),
        accounts_purged=len(accounts),
        capped=capped,
    )
    return {
        "meetups_purged": len(meetups),
        "accounts_purged": len(accounts),
        "backlog": capped,
    }


@router.post("/admin/accounts/{user_id}/disable")
def admin_disable_account(
    user_id: str,
    _: None = Depends(_require_admin),
    session: Session = Depends(get_session),
):
    """Disable an account and end its sessions.

    The minimum operation needed to stop a tester's access, per the Phase A
    requirement for a protected administrative path. It does not delete their
    meetup participation: removing that would silently rewrite other people's
    plans. Deletion and anonymisation are separate and deliberate.
    """
    _require_storage()
    if not disable_account(session, user_id):
        raise HTTPException(status_code=404, detail="No such account.")
    return {"ok": True, "user_id": user_id, "status": "disabled"}


@router.post("/auth/accept-beta-invite", response_model=AccountPublic)
def accept_beta_invite(
    request: Request,
    response: Response,
    body: AcceptInviteRequest,
    session: Session = Depends(get_session),
):
    """Exchange an invite for an account. The registration mode is enforced
    here, server-side, not by hiding a button.

    POST with the token in the body, so that neither a link preview nor an
    unauthenticated GET can consume an invitation, and the raw token never
    reaches an access log.
    """
    _require_storage()
    if registration_mode() is RegistrationMode.CLOSED:
        raise HTTPException(status_code=403, detail="Account creation is closed.")
    # With a provider configured, admission needs BOTH the invitation and a
    # verified identity: the invite says who may join, the token says who is
    # actually here. Either alone is not enough.
    identity = None
    if identity_configured():
        try:
            identity = verify_access_token(_bearer(request))
        except IdentityError as e:
            raise HTTPException(status_code=401, detail=str(e))

    try:
        account = accept_invite(
            session, body.invite_token,
            email=(identity.email if identity else body.email),
            display_name=body.display_name,
        )
        if identity is not None:
            link_identity(account, identity)
            session.commit()
    except IdentityError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except InviteError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if identity_configured():
        # A real provider is in play; the temporary cookie must not be minted
        # alongside it, or there would be two ways in and only one of them
        # verified.
        return _account_public(account)

    raw = open_session(session, account.id)
    # Secure is required in production but makes the cookie unusable over plain
    # http, which is how localhost and the test client run. Follow the scheme
    # of the actual request rather than hard-coding either answer.
    response.set_cookie(
        SESSION_COOKIE, raw,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=60 * 60 * 24 * 30,
    )
    return _account_public(account)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


def _current_account(request: Request, session: Session, cookie: Optional[str]):
    """The signed-in account, or None for an anonymous request.

    Delegates to core.current_user so that every surface agrees on what a
    credential means. The behaviour that changed: a token which is present but
    unusable now raises rather than quietly becoming an anonymous request.
    """
    try:
        return current_account(request, session, cookie)
    except CredentialsRejected as e:
        raise HTTPException(status_code=401, detail=str(e))


def _optional_account(request: Request, session: Session, cookie: Optional[str]):
    """Same, for endpoints that must keep working for guests.

    Meetups are joined by capability link and need no account at all, so an
    anonymous request here is ordinary. A *rejected* credential is still an
    error: someone whose session expired mid-flow should be told, not silently
    demoted to a guest and separated from their own meetup.
    """
    return _current_account(request, session, cookie)


@router.post("/auth/session", response_model=AccountPublic)
def exchange_token(
    request: Request,
    session: Session = Depends(get_session),
):
    """Confirm who an Auth0 access token belongs to.

    Does not create accounts. Admission is granted by redeeming an invitation,
    not by turning up with a valid sign-in - otherwise anyone who can sign in
    to Auth0 has an account here, and invite_only means nothing.
    """
    _require_storage()
    if not identity_configured():
        raise HTTPException(
            status_code=503,
            detail="Sign-in is not configured on this deployment.",
        )
    try:
        identity = verify_access_token(_bearer(request))
    except IdentityError as e:
        raise HTTPException(status_code=401, detail=str(e))

    account = account_for_identity(session, identity)
    if account is None:
        raise HTTPException(
            status_code=403,
            detail="You need an invitation before you can use an account here.",
        )
    return _account_public(account)


@router.get("/account/export")
def export_my_data(
    request: Request,
    driftway_staging_session: Optional[str] = Cookie(None),
    session: Session = Depends(get_session),
):
    """Everything held about you, as JSON.

    Includes your own exact starting points: they are yours, and the fact that
    they are sensitive is the reason you are entitled to see them, not a reason
    to withhold them. Other participants' origins are not included - those are
    not yours to receive.
    """
    _require_storage()
    account = _current_account(request, session, driftway_staging_session)
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    return export_account(session, account.id)


@router.delete("/account")
def erase_my_account(
    request: Request,
    response: Response,
    driftway_staging_session: Optional[str] = Cookie(None),
    session: Session = Depends(get_session),
):
    """Delete your account and everything linked to it. Not reversible."""
    _require_storage()
    account = _current_account(request, session, driftway_staging_session)
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    removed = erase_account(session, account.id)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True, "removed": removed}


@router.get("/auth/me", response_model=Optional[AccountPublic])
def me(
    request: Request,
    driftway_staging_session: Optional[str] = Cookie(None),
    session: Session = Depends(get_session),
):
    """Who the caller is, or null.

    Consulted the staging cookie only, which meant it answered null for every
    Auth0 session - the one deployment shape it now has to work in. Routed
    through the shared resolver so a bearer token counts here too.
    """
    if not storage_available():
        return None
    account = _current_account(request, session, driftway_staging_session)
    return _account_public(account) if account else None


@router.post("/auth/logout")
def logout(
    response: Response,
    driftway_staging_session: Optional[str] = Cookie(None),
    session: Session = Depends(get_session),
):
    if storage_available():
        close_session(session, driftway_staging_session)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


def _account_public(a: UserAccount) -> AccountPublic:
    # Note the absence of `email`: an account's login address is private and
    # never reaches a group-facing surface.
    return AccountPublic(
        id=a.id,
        display_name=a.display_name,
        status=a.status,
        default_hide_exact_origin=a.default_hide_exact_origin,
    )


# ------------------------------------------------------------------ meetups

def _parse_when(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="scheduled_at must be ISO-8601.")
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


@router.post("/meetups", response_model=MeetupCreated)
def create_meetup(
    req: CreateMeetupRequest,
    request: Request,
    _: None = Depends(_require_feature),
    driftway_staging_session: Optional[str] = Cookie(None),
    repo: SqlMeetupRepository = Depends(_repo),
    session: Session = Depends(get_session),
):
    """Start a meetup.

    Creating one signed in attaches it to that account, so it appears in the
    organiser's export and is removed with them. Creating one signed out still
    works and leaves the links null - the capability tokens returned below are
    the whole access model in that case, exactly as before.
    """
    _require_storage()
    account = _optional_account(request, session, driftway_staging_session)
    meetup = repo.create_meetup(
        scheduled_at=_parse_when(req.scheduled_at),
        mode=req.mode,
        requested_categories=",".join(req.categories),
        status="collecting",
    )

    lat, lng = coarsen(req.organiser.start.lat, req.organiser.start.lng)
    organiser, organiser_token = repo.add_participant(
        meetup_id=meetup.id,
        start_lat=req.organiser.start.lat,
        start_lng=req.organiser.start.lng,
        display_lat=lat,
        display_lng=lng,
        hide_exact_origin=req.organiser.hide_exact_origin,
        display_name=req.organiser.display_name,
        preferred_minutes=req.organiser.preferred_minutes,
        tolerance_minutes=req.organiser.tolerance_minutes,
        max_minutes=req.organiser.max_minutes,
    )
    meetup.owner_participant_id = organiser.id
    # Server-derived, both of them. There is no request field that can set
    # these, so no client can claim to organise on another account's behalf.
    if account is not None:
        meetup.owner_user_id = account.id
        organiser.user_id = account.id
    repo.touch_meetup(meetup)

    # A second, empty participant slot carrying its own write capability. The
    # organiser shares THIS token, never their own - handing over your own join
    # token would give the other parent your seat, not a seat of their own.
    invitee, invite_token = repo.add_participant(
        meetup_id=meetup.id, start_lat=0.0, start_lng=0.0, hide_exact_origin=True,
    )

    log.info(
        "meetup created: id=%s mode=%s categories=%d",
        meetup.id, meetup.mode, len(req.categories),
    )
    return MeetupCreated(
        meetup_id=meetup.id,
        your_join_token=organiser_token,
        participant_invite_token=invite_token,
        results_slug=meetup.public_results_slug,
    )


@router.post("/meetups/{meetup_id}/participants/{join_token}", response_model=MeetupPublic)
def join_meetup(
    meetup_id: str,
    join_token: str,
    req: JoinMeetupRequest,
    request: Request,
    _: None = Depends(_require_feature),
    driftway_staging_session: Optional[str] = Cookie(None),
    repo: SqlMeetupRepository = Depends(_repo),
    session: Session = Depends(get_session),
):
    """Set or update this participant's origin and preferences.

    No account required: `user_id` stays null for a guest. Putting a signup
    wall inside the collaboration funnel would kill the feature.

    A signed-in parent claims the seat instead, so that their participation -
    and the exact origin inside it - is covered by their own export and
    erasure. The capability that authorises the claim is the join token they
    already had to present; nothing is inferred from an email address, a
    display name or where they happen to be starting from. A seat already held
    by a different account is never reassigned.
    """
    _require_storage()
    account = _optional_account(request, session, driftway_staging_session)
    meetup = repo.get_meetup(meetup_id)
    if meetup is None:
        raise HTTPException(status_code=404, detail="Meetup not found.")

    participant = repo.participant_by_token(join_token)
    if participant is None or participant.meetup_id != meetup_id:
        # Deliberately identical to "no such meetup": a wrong token should not
        # confirm that a meetup exists.
        raise HTTPException(status_code=404, detail="Meetup not found.")

    if len(repo.participants(meetup_id)) > MAX_PARTICIPANTS_PER_MEETUP:
        raise HTTPException(status_code=409, detail="This meetup is full.")

    if account is not None:
        if participant.user_id and participant.user_id != account.id:
            # Someone else's seat. Holding the link is not enough to take it:
            # that would let a forwarded invitation overwrite the parent who
            # already filled it in, origin and all.
            raise HTTPException(
                status_code=409,
                detail="That place in the meetup belongs to another account.",
            )
        participant.user_id = account.id

    participant.start_lat = req.start.lat
    participant.start_lng = req.start.lng
    participant.hide_exact_origin = req.hide_exact_origin
    participant.display_name = req.display_name or participant.display_name
    participant.preferred_minutes = req.preferred_minutes
    participant.tolerance_minutes = req.tolerance_minutes
    participant.max_minutes = req.max_minutes
    participant.display_lat, participant.display_lng = coarsen(
        req.start.lat, req.start.lng
    )
    repo.save()

    return _view(repo, meetup, viewer_id=participant.id)


# NOTE ON ORDER: this literal path must be declared before
# "/meetups/{meetup_id}/{join_token}", which would otherwise match
# "/meetups/results/<slug>" with meetup_id="results" and swallow every
# results link. FastAPI resolves routes in declaration order.
@router.get("/meetups/results/{results_slug}", response_model=MeetupPublic)
def public_results(
    results_slug: str,
    _: None = Depends(_require_feature),
    repo: SqlMeetupRepository = Depends(_repo),
):
    """Read-only. No viewer identity, so every origin renders coarse and no
    join token appears anywhere in the payload."""
    _require_storage()
    meetup = repo.get_meetup_by_slug(results_slug)
    if meetup is None:
        raise HTTPException(status_code=404, detail="Results not found.")
    return _view(repo, meetup, viewer_id=None)


@router.get("/meetups/{meetup_id}/{join_token}", response_model=MeetupPublic)
def read_meetup(
    meetup_id: str,
    join_token: str,
    _: None = Depends(_require_feature),
    repo: SqlMeetupRepository = Depends(_repo),
):
    """A participant's own view: their exact origin, everyone else's coarse."""
    _require_storage()
    meetup = repo.get_meetup(meetup_id)
    participant = repo.participant_by_token(join_token)
    if meetup is None or participant is None or participant.meetup_id != meetup_id:
        raise HTTPException(status_code=404, detail="Meetup not found.")
    is_owner = meetup.owner_participant_id == participant.id
    return _view(repo, meetup, viewer_id=participant.id, include_slug=is_owner)


def _participant_or_404(repo, meetup_id: str, join_token: str):
    meetup = repo.get_meetup(meetup_id)
    participant = repo.participant_by_token(join_token)
    if meetup is None or participant is None or participant.meetup_id != meetup_id:
        raise HTTPException(status_code=404, detail="Meetup not found.")
    return meetup, participant


@router.post("/meetups/{meetup_id}/venues/{join_token}", response_model=MeetupPublic)
def add_venue(
    meetup_id: str,
    join_token: str,
    req: AddVenueRequest,
    _: None = Depends(_require_feature),
    repo: SqlMeetupRepository = Depends(_repo),
):
    """Put a venue into the shared pool.

    Both parents contribute places they already know suit their children. That
    judgement is the thing no provider taxonomy can supply, so the pool is the
    input the ranking works on.
    """
    _require_storage()
    meetup, participant = _participant_or_404(repo, meetup_id, join_token)

    existing = repo.find_near(meetup_id, req.coord.lat, req.coord.lng)
    if existing is not None:
        # Both parents naming the same place is agreement, not a conflict, so
        # this reports the overlap instead of creating a duplicate card.
        raise HTTPException(
            status_code=409,
            detail=f"{existing.name} is already on the list.",
        )
    if len(repo.candidates(meetup_id)) >= MAX_VENUE_CANDIDATES * 4:
        raise HTTPException(status_code=409, detail="That is enough places to compare.")

    # Adding a venue at your own doorstep publishes that coordinate, because a
    # venue location is legitimately public. That only matters to someone who
    # asked to stay hidden - parents who are sharing openly already know each
    # other's areas - so the warning is conditional on their own choice.
    self_reveal = (
        participant.hide_exact_origin
        and _rough_metres(
            participant.start_lat, participant.start_lng,
            req.coord.lat, req.coord.lng,
        ) <= SELF_REVEAL_METRES
    )

    repo.add_candidate(
        meetup_id,
        added_by_participant_id=participant.id,
        name=req.name,
        lat=req.coord.lat,
        lng=req.coord.lng,
        address_label=req.address_label,
        canonical_categories=",".join(req.categories),
        provider_rating=req.provider_rating,
        opening_status=req.opening_status,
        provider="pool",
    )
    notice = None
    if self_reveal:
        notice = (
            f"{req.name} is right where you set off from. You chose to keep "
            f"your starting point private, and a venue's location is shown to "
            f"everyone - so adding this reveals roughly where you are."
        )
    return _view(repo, meetup, viewer_id=participant.id, notice=notice)


@router.delete("/meetups/{meetup_id}/venues/{join_token}/{candidate_id}",
               response_model=MeetupPublic)
def remove_venue(
    meetup_id: str,
    join_token: str,
    candidate_id: str,
    _: None = Depends(_require_feature),
    repo: SqlMeetupRepository = Depends(_repo),
):
    """Withdraw a suggestion: your own, or any of them if you are the organiser."""
    _require_storage()
    meetup, participant = _participant_or_404(repo, meetup_id, join_token)

    row = repo.get_candidate(candidate_id)
    if row is None or row.meetup_id != meetup_id:
        raise HTTPException(status_code=404, detail="Venue not in this meetup.")

    is_owner = meetup.owner_participant_id == participant.id
    if row.added_by_participant_id != participant.id and not is_owner:
        raise HTTPException(
            status_code=403,
            detail="Only whoever suggested this place, or the organiser, can remove it.",
        )
    repo.delete_candidate(row)
    return _view(repo, meetup, viewer_id=participant.id)


@router.post("/meetups/{meetup_id}/candidates/{join_token}", response_model=MeetupPublic)
async def generate_candidates(
    meetup_id: str,
    join_token: str,
    road_profile: str = "mixed",
    _: None = Depends(_require_feature),
    repo: SqlMeetupRepository = Depends(_repo),
):
    """Work out what each place actually costs each parent, then rank them.

    One matrix call covers every participant against every venue, so this costs
    a single provider request regardless of how many of either there are.
    """
    _require_storage()
    meetup, participant = _participant_or_404(repo, meetup_id, join_token)

    participants = repo.participants(meetup_id)
    # An invited participant who has not set an origin yet still holds the
    # placeholder 0,0 and would otherwise be routed from the Atlantic.
    ready = [p for p in participants if p.start_lat or p.start_lng]
    venues = repo.candidates(meetup_id)

    if len(ready) < 2:
        return _view(
            repo, meetup, viewer_id=participant.id,
            notice="Waiting for the other parent to say where they are setting off from.",
        )
    if not venues:
        return _view(
            repo, meetup, viewer_id=participant.id,
            notice="Add a few places you both like, and each one will show what it costs each of you.",
        )

    routing = get_router()
    grid = await routing.travel_matrix(
        [Coord(lat=p.start_lat, lng=p.start_lng) for p in ready],
        [Coord(lat=v.lat, lng=v.lng) for v in venues],
        road_profile,
    )

    needs = [
        ParticipantNeed(
            participant_id=p.id,
            preferred_minutes=p.preferred_minutes,
            tolerance_minutes=p.tolerance_minutes,
            max_minutes=p.max_minutes,
        )
        for p in ready
    ]

    scores = []
    for j, venue in enumerate(venues):
        minutes = {
            ready[i].id: (grid[i][j] if i < len(grid) and j < len(grid[i]) else None)
            for i in range(len(ready))
        }
        scores.append(score_venue(
            j, minutes, needs,
            suitability=venue.suitability,
            opening_status=venue.opening_status,
            provider_rating=venue.provider_rating,
        ))

    result = rank_venues(scores, needs, limit=MAX_VENUE_CANDIDATES)

    # Persist the measurements so the results link and later votes read the
    # same numbers without paying for the matrix again.
    for rank, sc in enumerate(result.ordered):
        venue = venues[sc.venue_index]
        venue.travel_json = json.dumps(sc.travel)
        venue.fairness_spread_minutes = sc.spread
        venue.total_travel_minutes = sc.total_burden
        venue.max_travel_minutes = sc.max_burden
        venue.score = float(len(result.ordered) - rank)
        venue.score_breakdown = json.dumps(sc.breakdown)
    for sc in scores:
        if sc.unroutable:
            venues[sc.venue_index].score = -1.0
            venues[sc.venue_index].score_breakdown = json.dumps(sc.breakdown)
    meetup.status = "ready" if result.ordered else "collecting"
    repo.save()

    # Provider cost is part of the experiment, so it is counted explicitly.
    log.info(
        "meetup candidates: id=%s participants=%d venues=%d provider_calls=1 "
        "ranked=%d no_fit=%s",
        meetup_id, len(ready), len(venues), len(result.ordered), result.no_fit,
    )
    return _view(repo, meetup, viewer_id=participant.id,
                 notice=result.notice, no_fit=result.no_fit)


@router.post("/meetups/{meetup_id}/selection/{join_token}", response_model=MeetupPublic)
def select_venue(
    meetup_id: str,
    join_token: str,
    candidate_id: str,
    _: None = Depends(_require_feature),
    repo: SqlMeetupRepository = Depends(_repo),
):
    """Settle on a venue.

    The organiser decides, after the votes are in. A group rule (majority,
    unanimity) is a product question rather than an engineering one, and
    guessing at it would bake in a policy nobody chose - so for staging the
    person who created the meetup makes the call.
    """
    _require_storage()
    meetup, participant = _participant_or_404(repo, meetup_id, join_token)

    if meetup.owner_participant_id != participant.id:
        raise HTTPException(
            status_code=403,
            detail="Only whoever set up the meetup can choose the final place.",
        )

    row = repo.get_candidate(candidate_id)
    if row is None or row.meetup_id != meetup_id:
        raise HTTPException(status_code=404, detail="Venue not in this meetup.")

    meetup.selected_venue_id = candidate_id
    meetup.status = "decided"
    repo.save()
    log.info("meetup decided: id=%s", meetup_id)
    return _view(repo, meetup, viewer_id=participant.id, include_slug=True)


@router.delete("/meetups/{meetup_id}/selection/{join_token}", response_model=MeetupPublic)
def clear_selection(
    meetup_id: str,
    join_token: str,
    _: None = Depends(_require_feature),
    repo: SqlMeetupRepository = Depends(_repo),
):
    """Change your mind. Plans with small children rarely survive first
    contact, so undeciding has to be as easy as deciding."""
    _require_storage()
    meetup, participant = _participant_or_404(repo, meetup_id, join_token)
    if meetup.owner_participant_id != participant.id:
        raise HTTPException(
            status_code=403,
            detail="Only whoever set up the meetup can change the final place.",
        )
    meetup.selected_venue_id = None
    meetup.status = "ready"
    repo.save()
    return _view(repo, meetup, viewer_id=participant.id, include_slug=True)


@router.put("/meetups/{meetup_id}/votes/{candidate_id}", response_model=MeetupPublic)
def vote(
    meetup_id: str,
    candidate_id: str,
    req: VoteRequest,
    join_token: str,
    _: None = Depends(_require_feature),
    repo: SqlMeetupRepository = Depends(_repo),
):
    """One vote per participant per venue, upserted so repeat votes replace."""
    _require_storage()
    meetup = repo.get_meetup(meetup_id)
    participant = repo.participant_by_token(join_token)
    if meetup is None or participant is None or participant.meetup_id != meetup_id:
        raise HTTPException(status_code=404, detail="Meetup not found.")

    # A candidate id from another meetup must not be votable from this one.
    if not any(c.id == candidate_id for c in repo.candidates(meetup_id)):
        raise HTTPException(status_code=404, detail="Venue not in this meetup.")

    repo.upsert_vote(
        meetup_id=meetup_id,
        venue_candidate_id=candidate_id,
        participant_id=participant.id,
        value=req.value,
        comment=req.comment,
    )
    return _view(repo, meetup, viewer_id=participant.id)


def _view(repo, meetup, *, viewer_id, include_slug: bool = False,
          notice: Optional[str] = None, no_fit: bool = False) -> MeetupPublic:
    return meetup_public(
        meetup,
        repo.participants(meetup.id),
        repo.candidates(meetup.id),
        repo.votes(meetup.id),
        viewer_id=viewer_id,
        include_results_slug=include_slug,
        notice=notice,
        no_fit=no_fit,
    )
