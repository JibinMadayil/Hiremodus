"""Candidate replies on the candidate page: list, read, attachments, and answering from HireModus."""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, mailbox
from ..msgraph import transport_for
from ..perms import require, candidate_access
from ..services import queue_job, join_emails, split_emails, minus, audit, clean_email

router = APIRouter(tags=["replies"])


def _email(db, user, eid: int) -> tuple[models.CandidateEmail, models.Candidate]:
    e = db.get(models.CandidateEmail, eid)
    if not e:
        raise HTTPException(404, "Email not found")
    c = db.get(models.Candidate, e.candidate_id)
    if not c or candidate_access(db, user, c) != "full":
        raise HTTPException(403, "This candidate belongs to a department you don't work in")
    return e, c


def _mark_read(e: models.CandidateEmail, user):
    if user.id not in (e.read_by or []):
        e.read_by = list(e.read_by or []) + [user.id]


@router.get("/api/candidate-emails/{eid}")
def get_email(eid: int, user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    e, _ = _email(db, user, eid)
    _mark_read(e, user)
    db.commit()
    return mailbox.email_out(e, user, full=True)


@router.post("/api/candidates/{cid}/emails/read-all")
def read_all(cid: int, user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    c = db.get(models.Candidate, cid)
    if not c or candidate_access(db, user, c) != "full":
        raise HTTPException(404, "Candidate not found")
    for e in db.query(models.CandidateEmail).filter_by(candidate_id=cid):
        _mark_read(e, user)
    db.commit()
    return {"ok": True}


@router.get("/api/candidate-emails/{eid}/attachments/{idx}")
def attachment(eid: int, idx: int, user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    e, _ = _email(db, user, eid)
    atts = e.attachments or []
    if idx < 0 or idx >= len(atts) or not atts[idx].get("file"):
        raise HTTPException(404, "Attachment not found")
    path = os.path.join(mailbox.MAIL_DIR, str(e.id), atts[idx]["file"])
    if not os.path.exists(path):
        raise HTTPException(404, "The file is no longer stored")
    return FileResponse(path, filename=atts[idx]["name"], media_type="application/octet-stream")


@router.get("/api/candidate-emails/{eid}/reply-draft")
def reply_draft(eid: int, user=Depends(require("emails.send")), db: Session = Depends(get_db)):
    e, c = _email(db, user, eid)
    dept = db.get(models.Department, c.department_id) if c.department_id else None
    subj = e.subject or ""
    return {
        "to": e.from_addr,
        "dept_cc": join_emails(minus(split_emails(dept.cc_emails if dept else ""), [user.email, e.from_addr])),
        "subject": subj if subj.lower().startswith(("re:", "re :")) else f"RE: {subj}".strip(),
        "threaded": str(user.id) in (e.copies or {}),
        "via": transport_for(db, user),
    }


class ReplyIn(BaseModel):
    body: str
    cc: str = ""
    subject: str = ""


@router.post("/api/candidate-emails/{eid}/reply")
def reply(eid: int, body: ReplyIn, user=Depends(require("emails.send")), db: Session = Depends(get_db)):
    e, c = _email(db, user, eid)
    if not body.body.strip():
        raise HTTPException(400, "Write a message first")
    via = transport_for(db, user)
    mine = (e.copies or {}).get(str(user.id)) or {}
    payload = {
        "to": e.from_addr, "cc": join_emails(minus(split_emails(body.cc), [user.email, e.from_addr])),
        "subject": body.subject.strip() or f"RE: {e.subject}", "body": body.body.rstrip(), "quoted": mailbox.quote(e),
        "reply_to": e.id,
    }
    # answer the exact message when it's in this person's own mailbox, through the same route
    if mine.get("via") == via == "connector" and mine.get("id"):
        payload["entry_id"] = mine["id"]
    if mine.get("via") == via == "graph" and mine.get("id"):
        payload["graph_id"] = mine["id"]
    name = f"{c.first_name} {c.last_name}".strip()
    job = queue_job(db, user, "reply_mail", payload, f"Reply to {name}: {payload['subject']}", candidate_id=c.id)
    _mark_read(e, user)
    audit(db, user, "email_reply_sent", payload["subject"], candidate_id=c.id)
    db.commit()
    return {"ok": True, "job_id": job.id, "threaded": bool(payload.get("entry_id") or payload.get("graph_id"))}
