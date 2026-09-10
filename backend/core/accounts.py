"""
Minimal account registry and beta-access invitations.

Two things this deliberately is NOT:

  - It is not a password database. No repository auth provider exists yet, so
    inventing password storage and a reset flow here would be the worst kind of
    guess: security-critical, hard to remove, and certain to be replaced. What
    exists instead is a provider-agnostic seam (`AuthIdentity`) that a managed
    provider can be wired into later, plus a staging-only session cookie so the
    founder can test today.

  - It is not a place for travel data. An account carries identity, status and
    entitlement anchors. Exact origins, saved homes and meetup history live
    elsewhere and stay there. Registering must never be mistaken for consenting
    to share a location.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

log = logging.getLogger("driftway")

from .config import DEFAULT_INVITE_TTL_DAYS, RegistrationMode, registration_mode
from .db import Base, _now, _uuid


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

class UserAccount(Base):
    """Identity, security and entitlement anchor. Nothing about where a family
    drives belongs in this table."""

    __tablename__ = "user_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Filled in when a managed auth provider is adopted. Nullable now so a
    # staging account can exist before that decision is made.
    auth_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    auth_subject: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Private. Never serialised into any meetup- or group-facing payload.
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    plan_key: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # The account-level default only seeds a new participant's choice. It never
    # overrides a choice already made for a specific meetup.
    default_hide_exact_origin: Mapped[bool] = mapped_column(Boolean, default=True)


class BetaAccessInvite(Base):
    """A single-use capability to create one account. Not a meetup invitation
    and not a results link - see `capabilities.py` for why those stay separate."""

    __tablename__ = "beta_access_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Only the hash is stored. A leaked database should not yield usable
    # invites, and the raw token is shown exactly once, at creation.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_by_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    accepted_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Optional later hardening: bind an invite to one address.
    bound_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)


class StagingSession(Base):
    """A signed-in session for founder testing only.

    Explicitly temporary. It exists so the invite flow can be exercised end to
    end before a managed auth provider is chosen, and it is the first thing to
    delete once one is. The cookie carrying it must be HttpOnly.
    """

    __tablename__ = "staging_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

# 32 bytes of urlsafe randomness. Long enough that guessing is not a threat
# model, and carrying no email, coordinate or sequential id inside it.
_TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(raw: str) -> str:
    """SHA-256 of the raw token.

    Not a password hash, and deliberately not a slow one: these are
    high-entropy random tokens, so there is nothing to brute force, and a slow
    KDF on every request would only cost latency.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tokens_match(raw: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_token(raw), stored_hash)


# --------------------------------------------------------------------------
# Invite lifecycle
# --------------------------------------------------------------------------

class InviteError(RuntimeError):
    """Why an invite could not be accepted. The message is user-facing."""


def create_invite(
    session: Session,
    *,
    ttl_days: int = DEFAULT_INVITE_TTL_DAYS,
    bound_email: Optional[str] = None,
    created_by_user_id: Optional[str] = None,
) -> tuple:
    """Mint a beta-access invite. Returns (row, raw_token).

    The raw token is returned to the caller once and never stored.
    """
    raw = new_token()
    row = BetaAccessInvite(
        token_hash=hash_token(raw),
        created_by_user_id=created_by_user_id,
        created_by_admin=created_by_user_id is None,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(days=max(1, ttl_days)),
        bound_email=bound_email,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    # Log the id, never the token.
    log.info("beta invite created: id=%s ttl_days=%d", row.id, ttl_days)
    return row, raw


def invite_status(row: BetaAccessInvite, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if row.revoked_at is not None:
        return "revoked"
    if row.accepted_at is not None:
        return "accepted"
    if row.expires_at <= now:
        return "expired"
    return "unused"


def revoke_invite(session: Session, invite_id: str) -> bool:
    row = session.get(BetaAccessInvite, invite_id)
    if row is None or row.accepted_at is not None or row.revoked_at is not None:
        return False
    row.revoked_at = _now()
    session.commit()
    log.info("beta invite revoked: id=%s", invite_id)
    return True


def accept_invite(
    session: Session,
    raw_token: str,
    *,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
) -> UserAccount:
    """Exchange a valid invite for exactly one account.

    Every gate here is server-side. The registration mode is checked first, so
    a leaked invite is still useless while the door is closed.
    """
    mode = registration_mode()
    if mode is RegistrationMode.CLOSED:
        raise InviteError("Account creation is closed right now.")
    if mode is RegistrationMode.INVITE_ONLY and not raw_token:
        raise InviteError("An invitation is required to create an account.")

    row = session.execute(
        select(BetaAccessInvite).where(
            BetaAccessInvite.token_hash == hash_token(raw_token or "")
        )
    ).scalar_one_or_none()

    if row is None:
        # Same message for "no such invite" as for a bad token: there is
        # nothing to gain from telling a stranger which it was.
        raise InviteError("That invitation is not valid.")

    status = invite_status(row)
    if status == "accepted":
        raise InviteError("That invitation has already been used.")
    if status == "revoked":
        raise InviteError("That invitation has been revoked.")
    if status == "expired":
        raise InviteError("That invitation has expired.")

    if row.bound_email and email and row.bound_email.lower() != email.lower():
        raise InviteError("That invitation was issued for a different address.")

    account = UserAccount(
        email=email or row.bound_email,
        display_name=display_name,
        status="active",
    )
    session.add(account)
    session.flush()  # assign the id before we reference it

    row.accepted_at = _now()
    row.accepted_by_user_id = account.id
    session.commit()
    session.refresh(account)
    log.info("beta invite accepted: invite=%s account=%s", row.id, account.id)
    return account


# --------------------------------------------------------------------------
# Staging sessions
# --------------------------------------------------------------------------

STAGING_SESSION_TTL_DAYS = 30
SESSION_COOKIE = "driftway_staging_session"


def open_session(session: Session, user_id: str) -> str:
    """Create a staging session, returning the raw cookie value."""
    raw = new_token()
    session.add(StagingSession(
        token_hash=hash_token(raw),
        user_id=user_id,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(days=STAGING_SESSION_TTL_DAYS),
    ))
    session.commit()
    return raw


def account_for_session(session: Session, raw: Optional[str]) -> Optional[UserAccount]:
    if not raw:
        return None
    row = session.execute(
        select(StagingSession).where(StagingSession.token_hash == hash_token(raw))
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
        return None
    return session.get(UserAccount, row.user_id)


def close_session(session: Session, raw: Optional[str]) -> None:
    if not raw:
        return
    row = session.execute(
        select(StagingSession).where(StagingSession.token_hash == hash_token(raw))
    ).scalar_one_or_none()
    if row is not None:
        session.delete(row)
        session.commit()
