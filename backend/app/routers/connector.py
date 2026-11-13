"""Endpoints used by the HireModus Outlook Connector running next to each user's desktop Outlook,
plus the Outbox screens that show what the connector did."""
import io
import json
import os
import zipfile
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..security import connector_user
from ..perms import require, has
from ..services import apply_job_result, audit, simulate, run_simulated
from ..util import row
from ..msgraph import transport_for
from .. import mailbox

router = APIRouter(tags=["connector"])

CLAIM_TIMEOUT = timedelta(minutes=5)
CONNECTOR_DIR = os.environ.get("HIREMODUS_CONNECTOR_DIR",
                               os.path.join(os.path.dirname(__file__), "..", "..", "..", "connector"))


class Heartbeat(BaseModel):
    version: str = ""
    outlook_user: str = ""
    outlook_email: str = ""
    machine: str = ""


@router.post("/api/connector/heartbeat")
def heartbeat(body: Heartbeat, user=Depends(connector_user), db: Session = Depends(get_db)):
    user.connector_last_seen = datetime.utcnow()
    user.connector_info = body.model_dump()
    db.commit()
    return {"ok": True, "user": user.name}


@router.get("/api/connector/jobs")
def claim_jobs(limit: int = 10, user=Depends(connector_user), db: Session = Depends(get_db)):
    user.connector_last_seen = datetime.utcnow()
    if transport_for(db, user) == "graph":  # this person's mail goes through Microsoft 365 instead
        db.commit()
        return []
    stale = datetime.utcnow() - CLAIM_TIMEOUT
    # put back anything a crashed connector claimed but never finished (except mail, to avoid double sends)
    for j in db.query(models.OutboxJob).filter(models.OutboxJob.owner_id == user.id,
                                               models.OutboxJob.status == "claimed",
                                               models.OutboxJob.claimed_at < stale):
        if j.kind in ("free_busy",):
            j.status = "queued"
        else:
            j.status = "failed"
            j.error = "The connector stopped before confirming this. Check Outlook Sent Items / Calendar, then retry if it's missing."
            apply_job_result(db, j)
    jobs = (db.query(models.OutboxJob)
            .filter(models.OutboxJob.owner_id == user.id, models.OutboxJob.status == "queued")
            .order_by(models.OutboxJob.kind != "free_busy", models.OutboxJob.id).limit(limit).all())
    for j in jobs:
        j.status = "claimed"
        j.claimed_at = datetime.utcnow()
        j.attempts += 1
    db.commit()
    return [{"id": j.id, "kind": j.kind, "payload": j.payload} for j in jobs]


class Done(BaseModel):
    ok: bool
    result: dict | None = None
    error: str = ""


@router.post("/api/connector/jobs/{jid}/complete")
def complete(jid: int, body: Done, user=Depends(connector_user), db: Session = Depends(get_db)):
    j = db.get(models.OutboxJob, jid)
    if not j or j.owner_id != user.id:
        raise HTTPException(404, "Job not found")
    j.status = "done" if body.ok else "failed"
    j.result = body.result or {}
    j.error = body.error[:2000]
    j.completed_at = datetime.utcnow()
    apply_job_result(db, j)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- candidate replies

@router.get("/api/connector/watch")
def watch(user=Depends(connector_user), db: Session = Depends(get_db)):
    """Which senders to look for in this person's Inbox, and from when."""
    if not mailbox.enabled(db) or transport_for(db, user) == "graph":
        return {"enabled": False, "addresses": [], "since": None, "interval_seconds": 300}
    since = mailbox.scan_since(db, user.reply_scan_at)
    return {"enabled": True, "addresses": sorted(mailbox.watch_addresses(db, user)), "since": since.isoformat() + "Z",
            "interval_seconds": 300, "max_attachment_bytes": mailbox.MAX_ATTACHMENT}


class Replies(BaseModel):
    scanned_at: str  # UTC time the connector started this check
    messages: list[dict] = []
    final: bool = True  # False while more batches of the same check are coming


@router.post("/api/connector/replies")
def post_replies(body: Replies, user=Depends(connector_user), db: Session = Depends(get_db)):
    res = mailbox.ingest(db, user, body.messages, "connector")
    if body.final:
        try:
            user.reply_scan_at = datetime.fromisoformat(body.scanned_at.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            user.reply_scan_at = datetime.utcnow()
    db.commit()
    return res


# ---------------------------------------------------------------- outbox (staff)

@router.get("/api/jobs")
def list_jobs(status: str = "", mine: bool = False, user=Depends(require("emails.send")), db: Session = Depends(get_db)):
    q = db.query(models.OutboxJob)
    if mine or not has(user, "outbox.view_all"):
        q = q.filter(models.OutboxJob.owner_id == user.id)
    if status:
        q = q.filter(models.OutboxJob.status.in_(status.split(",")))
    q = q.filter(models.OutboxJob.kind != "free_busy")
    names = {u.id: u.name for u in db.query(models.User).all()}
    out = []
    for j in q.order_by(models.OutboxJob.id.desc()).limit(500):
        d = row(j, {"result"})
        d["owner_name"] = names.get(j.owner_id, "")
        out.append(d)
    return out


@router.get("/api/jobs/{jid}")
def get_job(jid: int, user=Depends(require("emails.send")), db: Session = Depends(get_db)):
    j = db.get(models.OutboxJob, jid)
    if not j:
        raise HTTPException(404, "Job not found")
    if not has(user, "outbox.view_all") and j.owner_id != user.id:
        raise HTTPException(403, "Not your job")
    return row(j)


@router.post("/api/jobs/{jid}/retry")
def retry(jid: int, user=Depends(require("emails.send")), db: Session = Depends(get_db)):
    j = db.get(models.OutboxJob, jid)
    if not j or (not has(user, "outbox.view_all") and j.owner_id != user.id):
        raise HTTPException(404, "Job not found")
    if j.status not in ("failed", "cancelled"):
        raise HTTPException(400, "Only failed or cancelled items can be retried")
    j.status, j.error, j.result = "queued", "", None
    j.owner_id = user.id  # retried from my Outlook
    if j.kind == "create_appointment" and j.interview_id:
        iv = db.get(models.Interview, j.interview_id)
        if iv:
            iv.status = "sending"
            iv.organizer_id = user.id
    if simulate(db):
        run_simulated(db, j)
    db.commit()
    return {"ok": True}


@router.post("/api/jobs/{jid}/cancel")
def cancel(jid: int, user=Depends(require("emails.send")), db: Session = Depends(get_db)):
    j = db.get(models.OutboxJob, jid)
    if not j or (not has(user, "outbox.view_all") and j.owner_id != user.id):
        raise HTTPException(404, "Job not found")
    if j.status != "queued":
        raise HTTPException(400, "Only queued items can be cancelled")
    j.status = "cancelled"
    if j.kind == "create_appointment" and j.interview_id:
        iv = db.get(models.Interview, j.interview_id)
        if iv:
            iv.status = "cancelled"
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- connector download

@router.get("/api/connector/download")
def download_connector(request: Request, user=Depends(require("emails.send")), db: Session = Depends(get_db)):
    if not user.connector_key:
        raise HTTPException(400, "Generate your connector key first")
    server = str(request.base_url).rstrip("/")
    cfg = {"server_url": server, "connector_key": user.connector_key, "poll_seconds": 5}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        base = os.path.abspath(CONNECTOR_DIR)
        for name in ("hiremodus_connector.py", "requirements.txt", "start_connector.bat", "README.txt"):
            p = os.path.join(base, name)
            if os.path.exists(p):
                z.write(p, f"HireModusConnector/{name}")
        z.writestr("HireModusConnector/config.json", json.dumps(cfg, indent=2))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="HireModusConnector.zip"'})
