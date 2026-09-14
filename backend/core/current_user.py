"""
Who is making this request — derived on the server, and nowhere else.

Two rules shape every function here.

**A client-supplied id is never proof of anything.** Driftway has carried an
anonymous per-device id since before accounts existed, and that id is still how
a signed-out parent's saved places are grouped. It is a convenience, not a
credential: anyone can send any value. So the moment a request is
authenticated, the device id stops deciding ownership and the account decides
instead.

**Presenting a broken credential is an error, not anonymity.** The previous
helper caught every verification failure and returned None, which quietly
turned an expired session into an anonymous request. For a read that is merely
confusing; for a write it is data loss, because the parent's saved place lands
in device storage they will never see again once they sign in properly. So a
token that is present but unusable raises, and only the *absence* of
credentials means anonymous.

That second rule is deliberately applied everywhere rather than only to
protected endpoints: "your session expired, sign in again" is always a better
answer than silently doing something else.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("driftway")

from fastapi import Request
from sqlalchemy.orm import Session

from .accounts import UserAccount, account_for_session
from .identity import (
    IdentityError,
    account_for_identity,
    is_configured as identity_configured,
    verify_access_token,
)

#: Name of the staging cookie. Only consulted while no provider is configured.
SESSION_COOKIE = "driftway_staging_session"


class CredentialsRejected(RuntimeError):
    """Credentials were presented and could not be accepted.

    Distinct from "no credentials were presented", which is an ordinary
    anonymous request and not an error at all.
    """


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


def current_account(
    request: Request,
    session: Session,
    cookie: Optional[str] = None,
) -> Optional[UserAccount]:
    """The account behind this request, or None if it is anonymous.

    Raises CredentialsRejected when a token was supplied but is expired,
    malformed, issued elsewhere, or otherwise unusable.

    Returning None for a *verified* identity with no Driftway account is
    correct and not an error: signing in to Auth0 and being admitted to the
    beta are separate things, and someone in that state genuinely has no
    account-scoped storage to write to. Callers that require admission check
    for None themselves and say so.
    """
    token = bearer_token(request)

    if token:
        if not identity_configured():
            # A token arriving at a deployment with no provider cannot be
            # verified by anyone. Refusing is the only honest answer.
            raise CredentialsRejected(
                "Sign-in is not configured on this deployment."
            )
        try:
            identity = verify_access_token(token)
        except IdentityError as e:
            raise CredentialsRejected(str(e))
        return account_for_identity(session, identity)

    if identity_configured():
        # A configured deployment must not also be enterable through the
        # temporary staging cookie, or there would be two doors and only one
        # of them verified.
        return None

    return account_for_session(session, cookie)


def owner_for_write(
    account: Optional[UserAccount], device_owner: Optional[str]
) -> str:
    """The owner id to store on a record the caller is creating.

    An admitted account owns its own records. Everyone else keeps using the
    device id, which is what makes saved places work with no account at all.
    """
    if account is not None:
        return account.id
    return (device_owner or "").strip()
