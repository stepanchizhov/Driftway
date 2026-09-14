"""
Verified identity via Auth0.

The rule this module exists to enforce: an identity is whatever Auth0's
signature says it is, and nothing the client tells us. A request carries an
access token; we verify it against the tenant's published public keys and take
the `sub` claim. An email in the payload is informational only — it never
selects an account, because anyone can put any email in a request body.

Verified against Auth0 documentation, 14 September 2026:

  Tenants          https://auth0.com/docs/get-started/auth0-overview/create-tenants
      Regions include EU, EU-2 and UK. The domain encodes the region as
      `[tenant].[locality].auth0.com`, so the domain alone tells you where the
      data lives. Region is fixed at creation.

  Token validation https://auth0.com/docs/secure/tokens/access-tokens/validate-access-tokens
      Verify the signature, the standard claims, and that the `aud` claim
      contains the API's identifier.

  JWKS             https://auth0.com/docs/secure/tokens/json-web-tokens/validate-json-web-tokens
      Public keys at `https://{domain}/.well-known/jwks.json`.

RS256, not HS256. The backend is a separate resource server, so it should hold
only a public key: with HS256 the signing secret would have to live here too,
and anything able to verify a token could also mint one.

Until AUTH0_DOMAIN and AUTH0_AUDIENCE are configured this module reports itself
unconfigured and nothing here runs. That state is deliberately visible on
/api/health rather than silently falling back to the staging session.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("driftway")

from sqlalchemy import select
from sqlalchemy.orm import Session

from .accounts import UserAccount
from .db import _now

PROVIDER = "auth0"


def auth0_domain() -> str:
    """e.g. driftway.uk.auth0.com — the locality segment is the data region."""
    return (os.getenv("AUTH0_DOMAIN") or "").strip()


def auth0_audience() -> str:
    """The API identifier configured in Auth0. Tokens must name it in `aud`."""
    return (os.getenv("AUTH0_AUDIENCE") or "").strip()


def is_configured() -> bool:
    return bool(auth0_domain() and auth0_audience())


class IdentityError(RuntimeError):
    """The token is absent, malformed, expired, or not for us."""


@dataclass(frozen=True)
class VerifiedIdentity:
    """What the provider's signature actually vouches for."""

    subject: str               # Auth0 `sub` — the stable identity key
    email: Optional[str]       # informational; never used to select an account
    email_verified: bool


# The JWKS client caches keys and refetches on rotation, so this is built once.
_jwks_client = None


def _client():
    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient
        _jwks_client = PyJWKClient(
            f"https://{auth0_domain()}/.well-known/jwks.json",
            cache_keys=True,
        )
    return _jwks_client


def verify_access_token(token: str) -> VerifiedIdentity:
    """Validate an Auth0 access token, or raise.

    Every check Auth0 documents is applied, and the algorithm is pinned to
    RS256 so a token cannot arrive claiming `alg: none` or a symmetric
    algorithm and talk its way past the signature check.
    """
    if not is_configured():
        raise IdentityError("Sign-in is not configured on this deployment.")
    if not token:
        raise IdentityError("No access token supplied.")

    import jwt

    try:
        signing_key = _client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=auth0_audience(),
            issuer=f"https://{auth0_domain()}/",
            options={"require": ["exp", "iat", "iss", "sub", "aud"]},
        )
    except jwt.ExpiredSignatureError:
        raise IdentityError("That sign-in has expired. Please sign in again.")
    except jwt.InvalidAudienceError:
        raise IdentityError("That token was issued for a different application.")
    except jwt.InvalidIssuerError:
        raise IdentityError("That token was not issued by the expected provider.")
    except Exception as e:  # noqa: BLE001 - signature, format, network
        # Deliberately vague to the caller; the detail goes to the log, not to
        # whoever is probing the endpoint.
        log.warning("access token rejected (%s)", type(e).__name__)
        raise IdentityError("That sign-in could not be verified.")

    subject = claims.get("sub")
    if not subject:
        raise IdentityError("That token carries no subject.")

    return VerifiedIdentity(
        subject=subject,
        email=claims.get("email"),
        email_verified=bool(claims.get("email_verified")),
    )


def account_for_identity(
    session: Session,
    identity: VerifiedIdentity,
    *,
    create: bool = False,
    display_name: Optional[str] = None,
) -> Optional[UserAccount]:
    """Find the account for a verified identity.

    Matched on (provider, subject) only. Never on email: two people can control
    the same address over time, an address can be changed at the provider, and
    an unverified one is simply a string the client sent. `create=True` is
    passed only where an invitation has already authorised admission.
    """
    account = session.execute(
        select(UserAccount).where(
            UserAccount.auth_provider == PROVIDER,
            UserAccount.auth_subject == identity.subject,
        )
    ).scalars().first()

    if account is not None:
        if account.status != "active":
            return None
        account.last_active_at = _now()
        session.commit()
        return account

    if not create:
        return None

    account = UserAccount(
        auth_provider=PROVIDER,
        auth_subject=identity.subject,
        email=identity.email if identity.email_verified else None,
        display_name=display_name,
        status="active",
        last_active_at=_now(),
    )
    session.add(account)
    session.flush()
    return account


def link_identity(account: UserAccount, identity: VerifiedIdentity) -> None:
    """Attach a verified identity to an account created before sign-in existed.

    Used when a staging-era account redeems against a real provider for the
    first time. Refuses to move an identity that already belongs elsewhere.
    """
    if account.auth_subject and account.auth_subject != identity.subject:
        raise IdentityError("That account is already linked to a different sign-in.")
    account.auth_provider = PROVIDER
    account.auth_subject = identity.subject
    if identity.email_verified and identity.email:
        account.email = identity.email
