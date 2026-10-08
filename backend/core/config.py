"""
Server-authoritative feature and registration settings.

Everything here is read from the environment and decided on the server. The
frontend may hide a button, but hiding a button is not a security control -
the brief is explicit about that, and so is common sense: anyone can POST to
an endpoint the UI never renders.
"""

from __future__ import annotations

import logging
import os
from enum import Enum

log = logging.getLogger("driftway")


class RegistrationMode(str, Enum):
    """Who may create an account."""

    CLOSED = "closed"            # nobody, not even with an invite
    INVITE_ONLY = "invite_only"  # only with a valid, unused beta invite
    OPEN = "open"                # anyone (not used during the closed test)


# Staging default. Deliberately the safest of the three that still allows
# founder testing: an unset or misspelled value must never fall through to
# open registration.
_DEFAULT_REGISTRATION_MODE = RegistrationMode.INVITE_ONLY


def registration_mode() -> RegistrationMode:
    raw = (os.getenv("REGISTRATION_MODE") or "").strip().lower()
    if not raw:
        return _DEFAULT_REGISTRATION_MODE
    try:
        return RegistrationMode(raw)
    except ValueError:
        log.error(
            "REGISTRATION_MODE=%r is not one of %s; falling back to %s",
            raw,
            [m.value for m in RegistrationMode],
            _DEFAULT_REGISTRATION_MODE.value,
        )
        return _DEFAULT_REGISTRATION_MODE


def walking_enabled() -> bool:
    """Feature flag for the pram and carrier walking experiment.

    Off by default, per the brief: shipping the code must not ship the feature.
    With it off, every walking endpoint answers 404 and the frontend shows no
    entry point, so driving and meetups behave exactly as before.
    """
    return (os.getenv("WALKING_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def meet_halfway_enabled() -> bool:
    """Feature flag for the whole Meet Halfway surface.

    Off by default: this is a staging experiment and must not appear in a
    production deploy just because the code shipped.
    """
    return (os.getenv("MEET_HALFWAY_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def admin_token() -> str:
    """Shared secret guarding the founder-only invite endpoints.

    A deliberate stopgap, not an auth system. It exists so the founder can
    mint beta invites before any managed auth provider is chosen, and it is
    checked with a constant-time comparison. When empty, the admin endpoints
    refuse every request rather than defaulting to open.
    """
    return (os.getenv("ADMIN_API_TOKEN") or "").strip()


def retention_trigger_token() -> str:
    """A secret that can run the retention purge and do nothing else.

    Held by whatever schedules retention - currently a GitHub Actions workflow -
    so that the scheduler never needs the admin token, which can also mint
    invitations and disable accounts. Least privilege, and here it is close to
    zero privilege: the purge selects by age, so calling it more often than
    scheduled deletes nothing that was not already due. A leaked trigger token
    lets someone run a job early that would have run anyway.
    """
    return (os.getenv("RETENTION_TRIGGER_TOKEN") or "").strip()


# How long a beta-access invite stays valid unless the founder overrides it.
DEFAULT_INVITE_TTL_DAYS = 14

# How close a suggested venue has to be to the suggester's own hidden origin
# before we point out that adding it gives their area away.
SELF_REVEAL_METRES = 150.0

# Caps that keep a staging experiment from becoming an expensive one.
MAX_PARTICIPANTS_PER_MEETUP = 8
MAX_VENUE_CANDIDATES = 5
