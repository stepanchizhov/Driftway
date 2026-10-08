"""
The walking experiment's API: one read-only endpoint.

Access, per the 14 Sep access policy: free for admitted beta accounts, and
nobody else. Two separate gates, checked in this order:

  1. WALKING_ENABLED. Off, and the endpoint does not exist (404) - the same
     shape as a deployment that never had the feature.
  2. An admitted account. Signing in to the identity provider is not enough;
     a beta invitation must have been redeemed. Hiding the button in the UI is
     not the control - this is.

Equipment and load arrive in the request body and are used for this one
assessment only. Nothing here is stored: the brief keeps pram and carrier
details device-local, and a server that never writes them cannot leak them.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.config import walking_enabled
from core.current_user import CredentialsRejected, current_account
from core.db import get_session, storage_available
from core.walking.catalogue import assess_all
from core.walking.profiles import CarrierSetup, PramSetup

log = logging.getLogger("driftway")
router = APIRouter()


class PramIn(BaseModel):
    wheels: Literal["compact", "standard", "all_terrain"] = "standard"
    width_cm: Optional[int] = Field(None, ge=30, le=150)
    double: bool = False


class CarrierIn(BaseModel):
    kind: Literal["soft", "framed"] = "soft"
    # Approximate, optional, and never stored. The bounds are sanity limits on
    # input, not statements about what is safe to carry.
    child_kg: Optional[float] = Field(None, ge=0, le=40)
    carrier_kg: Optional[float] = Field(None, ge=0, le=15)
    luggage_kg: Optional[float] = Field(None, ge=0, le=30)
    luggage_with: Literal["carrier_adult", "companion"] = "carrier_adult"


class AssessIn(BaseModel):
    profile: Literal["pram", "carrier"]
    minutes: Optional[int] = Field(None, ge=10, le=240)
    pram: Optional[PramIn] = None
    carrier: Optional[CarrierIn] = None


#: Shown with every response. Sources checked 8 Oct 2026.
GUIDANCE = {
    "carrier_soft": {
        "title": "Slings and soft carriers: TICKS",
        "points": [
            "Tight",
            "In view at all times",
            "Close enough to kiss",
            "Keep chin off the chest",
            "Supported back",
        ],
        "source": "The Lullaby Trust",
        "url": "https://www.lullabytrust.org.uk/baby-safety/baby-product-information/slings-and-carriers/",
        "reviewed": "Page last reviewed 1 February 2025",
    },
    "carrier_framed": {
        "title": "Framed carriers",
        "points": [
            "Weight limits and fit are specific to your carrier model. Follow "
            "its manufacturer's instructions rather than any general figure.",
        ],
        "source": "Manufacturer instructions",
        "url": None,
        "reviewed": None,
    },
    "outdoors": {
        "title": "Before you set off",
        "points": [
            "Surfaces change with the weather. A path mapped or reported firm "
            "can be muddy or flooded after rain.",
            "Riverside paths can flood. Take warning signs at their word on the day.",
        ],
        "source": None,
        "url": None,
        "reviewed": None,
    },
}

HANDOFF = (
    "Google Maps can take you to the start. It will not follow this walk or "
    "know about its steps, gates or surfaces, and may send you a different way."
)


def _require_admitted(request: Request, session: Session, cookie: Optional[str]):
    try:
        account = current_account(request, session, cookie)
    except CredentialsRejected as e:
        raise HTTPException(status_code=401, detail=str(e))
    if account is None:
        raise HTTPException(
            status_code=403,
            detail="Walks are part of the closed beta. Sign in with an "
                   "invited account to try them.",
        )
    return account


@router.post("/walks/assess")
def assess_walks(
    body: AssessIn,
    request: Request,
    driftway_staging_session: Optional[str] = Cookie(None),
    session: Session = Depends(get_session),
):
    if not walking_enabled():
        raise HTTPException(status_code=404, detail="Not found.")
    if not storage_available():
        # Admission lives in the database. Without it nobody can be shown to
        # be admitted, and an outage must never grant access by default.
        raise HTTPException(status_code=503,
                            detail="Walks are temporarily unavailable.")
    _require_admitted(request, session, driftway_staging_session)

    if body.profile == "pram":
        p = body.pram or PramIn()
        setup = PramSetup(wheels=p.wheels, width_cm=p.width_cm, double=p.double)
    else:
        c = body.carrier or CarrierIn()
        setup = CarrierSetup(kind=c.kind, child_kg=c.child_kg, carrier_kg=c.carrier_kg,
                             luggage_kg=c.luggage_kg, luggage_with=c.luggage_with)

    guidance = [GUIDANCE["outdoors"]]
    carried = None
    if body.profile == "carrier":
        guidance.insert(0, GUIDANCE["carrier_framed" if setup.kind == "framed"
                                    else "carrier_soft"])
        carried = setup.carried_kg()

    return {
        "walks": assess_all(body.profile, setup, body.minutes),
        "guidance": guidance,
        # The carrying adult's own arithmetic, echoed back - not a judgement.
        "carried_kg": carried,
        "handoff": HANDOFF,
    }
