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

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from core import roadworks
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
