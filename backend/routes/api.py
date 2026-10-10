"""API endpoints."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.accounts import UserAccount
from core.db import AppFeedback, Favourite, Feedback, get_session, storage_available
from core.version import APP_VERSION, build
from core.generator import generate_routes
from core.models import (
    Coord,
    FavouriteCreate,
    FavouriteOut,
    FeedbackRequest,
    GenerateRequest,
    GenerateResponse,
    SearchResponse,
)
from core.config import meet_halfway_enabled, registration_mode, walking_enabled
from core.identity import is_configured as identity_configured
from core.ratelimit import (RateLimited, SlidingWindowLimiter, _Window, check_generate,
                            client_address)
from core.current_user import (
    SESSION_COOKIE,
    CredentialsRejected,
    current_account,
    owner_for_write,
)


def _retention_status() -> dict | None:
    """Summary of the last scheduled retention run, or None if it never ran."""
    if not storage_available():
        return None
    try:
        from core.db import SessionLocal
        from core.retention import last_run
        session = SessionLocal()
        try:
            row = last_run(session)
        finally:
            session.close()
        if row is None:
            return None
        return {
            "last_run": row.ran_at.isoformat(),
            "meetups_purged": row.meetups_purged,
            "accounts_purged": row.accounts_purged,
            "backlog": row.capped,
        }
    except Exception:  # noqa: BLE001 - never let a status field break health
        return None


def _walk_generation() -> bool:
    from core.walking.generate import is_configured
    return is_configured()


def _pending_schema() -> list:
    """Outstanding migration steps, or [] when up to date."""
    if not storage_available():
        return []
    try:
        from core.migrations import pending_steps
        return pending_steps()
    except Exception:  # noqa: BLE001
        return []
from core.router import get_router
from core.search import SearchUnavailable, get_search

log = logging.getLogger("driftway")

router = APIRouter()


def _require_storage() -> None:
    """Guard the endpoints that genuinely need a database.

    503, not 500: the API is healthy, storage is not, and the client should be
    told the difference so it can degrade instead of showing a crash.
    """
    if not storage_available():
        raise HTTPException(
            status_code=503,
            detail="Saving is unavailable right now. Routes still work.",
        )


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    req: GenerateRequest,
    request: Request,
    driftway_staging_session: str | None = Cookie(None),
    session: Session = Depends(get_session),
):
    """Plan a set of loops.

    Open to everyone, signed in or not - this is the app's core job and putting
    an account in front of it would defeat the point. What it is not is
    unmetered: one generation costs many provider calls, so it is limited per
    caller and capped across the service. See core/ratelimit.py.

    Identity is optional here and used only to pick a better limit key, so an
    unverifiable token is not fatal: the request falls back to being limited by
    address rather than being refused. That is the opposite of the rule for
    account-owned writes, and deliberately so - this endpoint owns nothing.
    """
    account_id = None
    if storage_available():
        try:
            account = current_account(request, session, driftway_staging_session)
            account_id = account.id if account else None
        except CredentialsRejected:
            account_id = None

    try:
        check_generate(request, account_id)
    except RateLimited as limited:
        raise HTTPException(
            status_code=429,
            detail=(
                "Driftway is at its limit for the moment - too many routes "
                "being planned at once. Please try again shortly."
                if limited.scope == "service" else
                "That is a lot of routes in a short time. Please wait a moment "
                "and try again."
            ),
            headers={"Retry-After": str(limited.retry_after)},
        )

    routing = get_router()
    result = await generate_routes(req, routing)
    if not result.routes:
        # Not an error exactly, but the client should know nothing usable came back.
        raise HTTPException(
            status_code=422,
            detail="No drivable loop found for these settings. Try a different "
                   "duration, road profile, or a wider tolerance.",
        )
    return result


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, max_length=120),
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
    limit: int = Query(6, ge=1, le=10),
):
    """Address, postcode and place lookup for both endpoint pickers.

    Proxied through the backend so the provider key never reaches the browser.
    An empty result list is a normal answer meaning "no matches"; only a
    provider failure is an error, and the two must stay distinguishable or the
    UI cannot tell the user which happened.
    """
    provider = get_search()
    near = Coord(lat=lat, lng=lng) if lat is not None and lng is not None else None
    try:
        places = await provider.search(q, near, limit)
    except SearchUnavailable as e:
        # 503, not 500: the app is fine, the upstream is not.
        raise HTTPException(status_code=503, detail=str(e))
    # Deliberately logs the count and not the query - the query is somebody's
    # home address.
    log.info("search: provider=%s results=%d", provider.name, len(places))
    return SearchResponse(query=q, places=places, provider=provider.name)


class AppFeedbackRequest(BaseModel):
    """A remark about the app, from any tab. Free text, so it is capped, and
    the screen asks people not to put addresses in it."""
    context: Literal["stillasleep", "plan", "meetup", "walk", "settings"]
    message: str = Field(..., min_length=1, max_length=2000)
    app_version: Optional[str] = Field(None, max_length=16)
    build: Optional[str] = Field(None, max_length=16)
    owner: Optional[str] = Field(None, max_length=64)


#: Anyone can send it, so it is metered: per sender, and across the service.
_app_feedback_caller = SlidingWindowLimiter()
_app_feedback_global = SlidingWindowLimiter()


@router.post("/feedback/app")
def app_feedback(
    fb: AppFeedbackRequest,
    request: Request,
    driftway_staging_session: str | None = Cookie(None),
    session: Session = Depends(get_session),
):
    """Feedback about the app itself - 0.8, so beta testers can report from
    wherever they are. Attributed like route feedback: to the account when
    signed in (so it is exported and erased with it), else to the device."""
    _require_storage()
    account = _account(request, session, driftway_staging_session)
    caller = f"account:{account.id}" if account else f"ip:{client_address(request)}"
    try:
        _app_feedback_global.check("*", [_Window(86400, 500)], scope="service")
        _app_feedback_caller.check(caller, [_Window(3600, 10)], scope="caller")
    except RateLimited as limited:
        raise HTTPException(status_code=429,
                            detail="Thanks - that's a lot of feedback at once. "
                                   "Please try again a little later.",
                            headers={"Retry-After": str(limited.retry_after)})
    row = AppFeedback(owner=owner_for_write(account, fb.owner), context=fb.context,
                      message=fb.message.strip(), app_version=fb.app_version,
                      build=fb.build)
    session.add(row)
    session.commit()
    # The message is not logged: people may write anything in it.
    log.info("app feedback stored: context=%s version=%s", fb.context, fb.app_version)
    return {"ok": True, "id": row.id}


@router.post("/feedback")
def feedback(
    fb: FeedbackRequest,
    request: Request,
    driftway_staging_session: str | None = Cookie(None),
    session: Session = Depends(get_session),
):
    # Persist to the database (SQLite locally, Postgres on Render).
    # Attributed the same way saved places are, so that a signed-in parent's
    # feedback is actually included in their export and removed on erasure.
    _require_storage()
    account = _account(request, session, driftway_staging_session)
    row = Feedback(
        owner=owner_for_write(account, fb.owner),
        route_id=fb.route_id,
        predicted_minutes=fb.predicted_minutes,
        actual_minutes=fb.actual_minutes,
        would_use_again=fb.would_use_again,
        baby_slept=fb.baby_slept,
        notes=fb.notes,
    )
    session.add(row)
    session.commit()
    log.info("feedback stored: route=%s would_use_again=%s", fb.route_id, fb.would_use_again)
    return {"ok": True, "id": row.id}


def _fallbacks() -> dict:
    from core import ors
    from core.router import tomtom_status
    return {
        "driving_and_search": "openrouteservice" if ors.configured() else None,
        "tomtom_stood_down": not tomtom_status()["available"],
        "walks_second_address": bool(ors.fallback()),
    }


@router.get("/health/providers")
async def health_providers():
    """One small real call to each outside service, at most every few hours.

    Run daily by .github/workflows/providers.yml, whose run fails - and so
    emails the repository owner - when any provider is not answering. Added
    10 Oct 2026, after openrouteservice moved its API and walks failed for a
    day before anyone knew. See core/provider_check.py.
    """
    from core.provider_check import cached_checks
    return await cached_checks()


@router.get("/health")
async def health():
    # Storage is reported separately from overall health on purpose: the API
    # is genuinely usable without it, and a crash-looping service tells you
    # far less than one that says which part is down.
    return {
        "status": "ok",
        # Which release and commit is answering, so a tester can tell whether
        # the app on their phone and the server are from the same build.
        "version": {"app": APP_VERSION, "build": build()},
        # What stands in when TomTom fails, and whether it is standing in now.
        "fallbacks": _fallbacks(),
        "provider": get_router().name,
        "search": get_search().name,
        "storage": "ok" if storage_available() else "unavailable",
        # Non-empty means a schema step has not been applied, so some feature
        # will fail even though storage itself answers. Reported separately
        # for the same reason storage is: a partial failure that looks healthy
        # is the hardest kind to diagnose.
        "schema_pending": _pending_schema(),
        # "auth0" once a tenant is configured, "staging" while the temporary
        # session mechanism is the only way in. Never let this read "auth0"
        # without a real tenant behind it - that is the misreport the whole
        # Phase A gate exists to prevent.
        "identity": "auth0" if identity_configured() else "staging",
        # So the sign-in screen can ask for an invitation only when one is
        # actually required, rather than guessing.
        "registration": registration_mode().value,
        # Whether the scheduled purge is a behaviour or only a policy. Absent
        # until a run completes against THIS database, which is what makes a
        # configured cron verifiable rather than assumed.
        "retention": _retention_status(),
        # Whether the walking experiment exists on this deployment. The
        # frontend shows its entry point only when this is true.
        "walking": walking_enabled(),
        # Whether walks can be made from any start (an openrouteservice key is
        # configured). Reports configuration, not that the service is up.
        "walk_generation": _walk_generation(),
        # The client uses this to decide whether to offer the staging entry
        # point at all, rather than showing a button that 404s.
        "meet_halfway": meet_halfway_enabled(),
    }


def _account(request: Request, session: Session, cookie):
    """The signed-in account, or None. 401 if credentials were bad.

    Every endpoint below that touches per-person data goes through here rather
    than believing an `owner` value from the request.
    """
    try:
        return current_account(request, session, cookie)
    except CredentialsRejected as e:
        raise HTTPException(status_code=401, detail=str(e))


def _device_owner(session: Session, owner: str) -> str:
    """The supplied id, but only if it is safe to treat as a device id.

    The device id is a bearer-ish secret: knowing it is how a signed-out
    browser reaches its own saved places. Account ids are not secret in the
    same way - they appear in exports and are handed around internally - so a
    request that presents one where a device id belongs is either confused or
    probing. Either way it must not be served, or "also show me this device's
    rows" becomes "also show me that account's rows".
    """
    owner = (owner or "").strip()
    if not owner:
        return ""
    if session.get(UserAccount, owner) is not None:
        return ""
    return owner


def _fav_out(f: Favourite, scope: str) -> FavouriteOut:
    return FavouriteOut(
        id=f.id,
        label=f.label,
        place_label=f.place_label,
        duration_minutes=f.duration_minutes,
        distance_km=f.distance_km,
        road_profile=f.road_profile,
        character=f.character,
        maps_url=f.maps_url,
        created_at=f.created_at.isoformat(),
        scope=scope,
    )


@router.post("/favourites", response_model=FavouriteOut)
def create_favourite(
    fav: FavouriteCreate,
    request: Request,
    driftway_staging_session: str | None = Cookie(None),
    session: Session = Depends(get_session),
):
    """Save a drive.

    Works signed out - saved places are one of the things the alpha gives away
    without an account. What changes when signed in is only *whose* it is, and
    that is decided here rather than by the `owner` the client sent.

    A rejected credential fails the write. It must never fall through to the
    anonymous path: the parent would get a saved place filed under a device id
    they can no longer see once they sign in properly.
    """
    _require_storage()
    account = _account(request, session, driftway_staging_session)
    row = Favourite(
        owner=owner_for_write(account, fav.owner),
        label=fav.label,
        place_label=fav.place_label,
        duration_minutes=fav.duration_minutes,
        distance_km=fav.distance_km,
        road_profile=fav.road_profile,
        character=fav.character,
        maps_url=fav.maps_url,
    )
    if not row.owner:
        raise HTTPException(
            status_code=422,
            detail="Saving needs either a device id or a signed-in account.",
        )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _fav_out(row, "account" if account else "device")


@router.get("/favourites", response_model=list[FavouriteOut])
def list_favourites(
    request: Request,
    owner: str,
    driftway_staging_session: str | None = Cookie(None),
    session: Session = Depends(get_session),
):
    """Saved drives for whoever is asking.

    Signed in, that is the account's own - and the `owner` in the query string
    is ignored for that purpose, so passing somebody else's id reveals nothing.

    Places saved on this device *before* signing in are returned too, marked
    scope="device". They are deliberately NOT claimed automatically: a device
    can be shared, and silently absorbing whatever was on it into the account
    of whoever signed in most recently would attach one person's saved places -
    including where they drive from - to another person's account. Claiming is
    a separate, explicit action.
    """
    _require_storage()
    account = _account(request, session, driftway_staging_session)

    def _for(owner_id: str, scope: str):
        if not owner_id:
            return []
        rows = (
            session.query(Favourite)
            .filter(Favourite.owner == owner_id)
            .order_by(Favourite.created_at.desc())
            .all()
        )
        return [_fav_out(f, scope) for f in rows]

    if account is None:
        return _for(owner, "device")

    out = _for(account.id, "account")
    # Only surface device rows for a genuine device id, never for something
    # that names an account.
    device = _device_owner(session, owner)
    if device and device != account.id:
        out += _for(device, "device")
    return out


@router.post("/favourites/claim", response_model=list[FavouriteOut])
def claim_favourites(
    request: Request,
    owner: str = Query(..., min_length=1, max_length=64),
    driftway_staging_session: str | None = Cookie(None),
    session: Session = Depends(get_session),
):
    """Move this device's saved places onto the signed-in account.

    Explicit and user-initiated, for the shared-device reason above. It moves
    only rows still owned by the device id the caller presented, and only onto
    the caller's own account - there is no form of this request that can take
    somebody else's records, because the destination is never client-supplied.

    Repeating it is harmless: rows already moved no longer match.
    """
    _require_storage()
    account = _account(request, session, driftway_staging_session)
    if account is None:
        raise HTTPException(
            status_code=401,
            detail="Sign in before moving saved places to an account.",
        )
    device = _device_owner(session, owner)
    if not device or device == account.id:
        # Includes the case where `owner` names another account. Claiming is
        # for a browser's own anonymous rows and nothing else.
        raise HTTPException(
            status_code=422,
            detail="That is not a set of saved places this device can move.",
        )

    rows = session.query(Favourite).filter(Favourite.owner == device).all()
    for row in rows:
        row.owner = account.id
    session.commit()
    log.info("claimed %d device favourites onto an account", len(rows))
    return [_fav_out(f, "account") for f in rows]


@router.delete("/favourites/{fav_id}")
def delete_favourite(
    fav_id: str,
    request: Request,
    owner: str,
    driftway_staging_session: str | None = Cookie(None),
    session: Session = Depends(get_session),
):
    """Remove a saved drive.

    A signed-in caller may delete their account's rows, and still the device
    rows this browser holds - but never a row belonging to another account,
    because the owner matched against is derived here, not accepted.
    """
    _require_storage()
    account = _account(request, session, driftway_staging_session)
    if account is None:
        permitted = [owner]
    else:
        permitted = [account.id]
        device = _device_owner(session, owner)
        if device and device != account.id:
            permitted.append(device)

    row = (
        session.query(Favourite)
        .filter(Favourite.id == fav_id, Favourite.owner.in_(permitted))
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Favourite not found.")
    session.delete(row)
    session.commit()
    return {"ok": True}
