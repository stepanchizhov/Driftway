"""
Street Manager open data arrives here (core/roadworks.py): Amazon SNS posts
each notification, signed. Unsigned or foreign messages are refused; a
subscription confirmation for a Street Manager topic is confirmed; a permit
notification updates the works kept for drives.

Registration (the founder): https://www.gov.uk/guidance/find-and-use-roadworks-data
with this endpoint, https://driftway.onrender.com/api/roadworks/street-manager,
subscribed to the permit topic.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from core import roadworks
from core.config import admin_token
from core.db import get_session, storage_available

log = logging.getLogger("driftway")
router = APIRouter()

MAX_BODY = 512 * 1024


@router.post("/roadworks/street-manager")
async def street_manager(request: Request, session: Session = Depends(get_session)):
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(status_code=413, detail="Too large.")
    try:
        msg = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Not JSON.")
    if not isinstance(msg, dict) or not await run_in_threadpool(roadworks.verify, msg):
        # Enough to tell a real Street Manager message we refuse (a topic we
        # don't know, say) from noise; none of it is secret.
        if isinstance(msg, dict) and msg.get("TopicArn"):
            log.warning("Street Manager message refused: %s from %s", msg.get("Type"), msg.get("TopicArn"))
        raise HTTPException(status_code=403, detail="Not a signed Street Manager message.")
    kind = msg.get("Type")
    if kind == "SubscriptionConfirmation":
        ok = await run_in_threadpool(roadworks.confirm_subscription, msg)
        return {"confirmed": ok}
    if kind != "Notification":
        return {"ignored": kind}
    if not storage_available():
        # SNS retries; better than dropping the work silently.
        raise HTTPException(status_code=503, detail="Storage unavailable.")
    try:
        payload = json.loads(msg.get("Message") or "{}")
    except ValueError:
        return {"ignored": "message not JSON"}
    row = roadworks.handle_event(session, payload)
    return {"kept": bool(row)}


@router.get("/admin/provider-usage")
def provider_usage(x_admin_token: Optional[str] = Header(None)):
    """Founder only: provider calls since this server started, per API and
    per operation, calls per drive request, and Driftway's own ceilings
    (core/usage.py). Nothing about anyone: counts only."""
    admin = admin_token()
    if not admin:
        raise HTTPException(status_code=503, detail="Admin access is not configured on this deployment.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, admin):
        raise HTTPException(status_code=403, detail="Not permitted.")
    from core import usage
    return usage.summary()


@router.get("/admin/roadworks/summary")
def roadworks_summary(x_admin_token: Optional[str] = Header(None),
                      session: Session = Depends(get_session)):
    """Founder only: what Street Manager has sent since the API started, and
    what is kept for drives."""
    admin = admin_token()
    if not admin:
        raise HTTPException(status_code=503, detail="Admin access is not configured on this deployment.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, admin):
        raise HTTPException(status_code=403, detail="Not permitted.")
    if not storage_available():
        raise HTTPException(status_code=503, detail="Storage unavailable.")
    return roadworks.summary(session)
