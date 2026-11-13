from datetime import datetime, timedelta, date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..perms import require, limit_full
from ..services import (audit, queue_job, queue_mail, queue_it_notice, candidate_context, render, fmt_date,
                        fmt_time, join_emails, split_emails, minus, local_now, get_setting, clean_email,
                        build_template_email)
from ..scheduling import FreeBusy, find_slots, evaluate, emails_to_check, search_range, no_check_attendees, ME
from ..testsvc import create_assignment, test_ctx
from ..util import row, rows, get_or_404
from .candidates import check_visible

router = APIRouter(prefix="/api/interviews", tags=["interviews"])


def holidays(db: Session) -> set[date]:
    return {h.day for h in db.query(models.Holiday).all()}


@router.get("")
def list_interviews(days_back: int = 1, days_ahead: int = 60, user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    now = local_now()
    q = (db.query(models.Interview, models.Candidate)
         .join(models.Candidate, models.Candidate.id == models.Interview.candidate_id)
         .filter(models.Interview.start >= now - timedelta(days=days_back),
                 models.Interview.start <= now + timedelta(days=days_ahead))
         .order_by(models.Interview.start))
    q = limit_full(q, db, user)
    out = []
    for iv, c in q.all():
        d = row(iv)
        d["candidate_name"] = f"{c.first_name} {c.last_name}".strip()
        d["candidate_department_id"] = c.department_id
        out.append(d)
    return out


# ---------------------------------------------------------------- availability

class AvailIn(BaseModel):
    candidate_id: int
    template_id: int
    from_date: str | None = None  # used by reschedule: search from a given date


@router.post("/availability")
def request_availability(body: AvailIn, user=Depends(require("interviews.schedule")), db: Session = Depends(get_db)):
    c = check_visible(db, user, body.candidate_id)
    tpl = get_or_404(db, models.InterviewTemplate, body.template_id, "Interview template")
    now = local_now()
    fd = date.fromisoformat(body.from_date) if body.from_date else None
    d0, d1 = search_range(tpl, now, fd)
    payload = {
        "emails": emails_to_check(tpl),
        "start_date": d0.isoformat(),
        "days": (d1 - d0).days + 1,
        "template_id": tpl.id,
        "from_date": body.from_date,
    }
    job = queue_job(db, user, "free_busy", payload, f"Check calendars for {tpl.name}: {c.first_name} {c.last_name}", c.id)
    db.commit()
    return {"job_id": job.id, "status": job.status}


@router.get("/availability/{job_id}")
def availability_result(job_id: int, user=Depends(require("interviews.schedule")), db: Session = Depends(get_db)):
    job = get_or_404(db, models.OutboxJob, job_id, "Calendar check")
    if job.owner_id != user.id:
        raise HTTPException(403, "That calendar check belongs to someone else")
    out = {"job_id": job.id, "status": job.status, "error": job.error}
    if job.status != "done":
        return out
    tpl = get_or_404(db, models.InterviewTemplate, job.payload["template_id"], "Interview template")
    fb = FreeBusy(job.result)
    fd = date.fromisoformat(job.payload["from_date"]) if job.payload.get("from_date") else None
    out["slots"] = find_slots(tpl, fb, local_now(), holidays(db), fd)
    out["unresolved"] = [e for e, v in (job.result or {}).get("free_busy", {}).items()
                         if e != ME and not v.get("resolved")]
    return out


class EvalIn(BaseModel):
    template_id: int
    start: str
    job_id: int | None = None


@router.post("/evaluate")
def evaluate_time(body: EvalIn, user=Depends(require("interviews.schedule")), db: Session = Depends(get_db)):
    tpl = get_or_404(db, models.InterviewTemplate, body.template_id, "Interview template")
    start = datetime.fromisoformat(body.start)
    if not body.job_id:
        return no_check_attendees(tpl, start)
    job = get_or_404(db, models.OutboxJob, body.job_id, "Calendar check")
    fb = FreeBusy(job.result if job.status == "done" else None)
    return evaluate(tpl, fb, start, local_now(), holidays(db))


# ---------------------------------------------------------------- invite text

def pick_module(db, c: models.Candidate, tpl: models.InterviewTemplate, module_id: int | None) -> models.Module | None:
    if module_id:
        return db.get(models.Module, module_id)
    if tpl.reuse_previous_module and c.module_id:
        return db.get(models.Module, c.module_id)
    return None


def invite_ctx(db, c, tpl, user, start: datetime, mod: models.Module | None) -> dict:
    ctx = candidate_context(db, c, user)
    end = start + timedelta(minutes=tpl.duration_min)
    ctx.update({
        "interview_date": fmt_date(start), "interview_time": fmt_time(start), "interview_end_time": fmt_time(end),
        "location": tpl.location, "round": tpl.round_label,
    })
    if mod:
        ctx.update({"module": mod.name, "module_web_link": mod.web_link, "module_training_link": mod.training_link})
    # test placeholders stay as-is until the real credentials exist
    for k in ("test_block", "test_name", "test_username", "test_password", "test_portal_url"):
        ctx[k] = "{{" + k + "}}"
    return ctx


class PreviewIn(BaseModel):
    candidate_id: int
    template_id: int
    start: str
    module_id: int | None = None


@router.post("/preview")
def preview(body: PreviewIn, user=Depends(require("interviews.schedule")), db: Session = Depends(get_db)):
    c = check_visible(db, user, body.candidate_id)
    tpl = get_or_404(db, models.InterviewTemplate, body.template_id, "Interview template")
    mod = pick_module(db, c, tpl, body.module_id)
    if tpl.requires_module and not mod:
        raise HTTPException(400, "Pick a training module for this interview")
    ctx = invite_ctx(db, c, tpl, user, datetime.fromisoformat(body.start), mod)
    test = pick_test(db, tpl, mod)
    return {
        "subject": render(tpl.invite_subject, ctx),
        "body": render(tpl.invite_body, ctx),
        "module_id": mod.id if mod else None,
        "includes_test": bool(tpl.includes_test and test),
        "test_id": test.id if test else None,
        "test_name": test.name if test else "",
        "test_from_module": bool(test and mod and mod.test_id == test.id),
    }


def pick_test(db, tpl: models.InterviewTemplate, mod: models.Module | None, override: int | None = None):
    """The module's own test wins (GL module -> GL questionnaire), then the interview type's default."""
    if not tpl.includes_test:
        return None
    for tid in (override, mod.test_id if mod else None, tpl.test_id):
        if tid:
            t = db.get(models.Test, tid)
            if t and t.active:
                return t
    return None


# ---------------------------------------------------------------- booking

class BookIn(BaseModel):
    candidate_id: int
    template_id: int
    start: str
    required: list[str]
    optional: list[str] = []
    module_id: int | None = None
    extra_cc: str = ""
    subject: str
    body: str
    include_test: bool = True
    test_id: int | None = None
    send_confirmation: bool = True


@router.post("")
def book(body: BookIn, user=Depends(require("interviews.schedule")), db: Session = Depends(get_db)):
    c = check_visible(db, user, body.candidate_id)
    if not c.email:
        raise HTTPException(400, "This candidate has no email address")
    tpl = get_or_404(db, models.InterviewTemplate, body.template_id, "Interview template")
    mod = pick_module(db, c, tpl, body.module_id)
    if tpl.requires_module and not mod:
        raise HTTPException(400, "Pick a training module for this interview")
    start = datetime.fromisoformat(body.start)
    end = start + timedelta(minutes=tpl.duration_min)
    cand_email = clean_email(c.email)
    required = minus(split_emails(join_emails(body.required)), [cand_email])
    optional = minus(split_emails(join_emails(body.optional, body.extra_cc)), required + [cand_email])

    iv = models.Interview(candidate_id=c.id, template_id=tpl.id, title=render(body.subject, {}), round_number=tpl.round_number,
                          start=start, end=end, location=tpl.location, required=join_emails([cand_email], required),
                          optional=join_emails(optional), module_id=mod.id if mod else None, organizer_id=user.id)
    db.add(iv)
    db.flush()

    ctx = {}
    test = pick_test(db, tpl, mod, body.test_id) if body.include_test else None
    if test:
        a, pw = create_assignment(db, c, test, iv.id)
        ctx = test_ctx(db, a, pw, test)
        audit(db, user, "test_assigned", f"{test.name} (login {a.username})", c.id)
    if not ctx:
        ctx = {"test_block": "", "test_name": "", "test_username": "", "test_password": "", "test_portal_url": ""}
    subject = render(body.subject, ctx)
    text = render(body.body, ctx)
    iv.title, iv.body = subject, text

    queue_job(db, user, "create_appointment", {
        "subject": subject, "body": text, "start": start.isoformat(), "end": end.isoformat(),
        "location": tpl.location, "required": iv.required, "optional": iv.optional,
    }, f"Invite: {subject}", c.id, iv.id)

    if body.send_confirmation and tpl.send_confirmation_email:
        cctx = invite_ctx(db, c, tpl, user, start, mod)
        queue_mail(db, user, {
            "to": cand_email, "cc": join_emails(minus(required + optional, [user.email])),
            "subject": render(render(tpl.confirmation_subject, cctx), ctx), "body": text,
        }, f"Confirmation email: {c.first_name} {c.last_name}", c.id, iv.id)

    if tpl.notify_it and tpl.it_links.strip():
        links = render(tpl.it_links, invite_ctx(db, c, tpl, user, start, mod))
        queue_it_notice(db, user, c, f"{tpl.round_label} materials", links)

    if mod and tpl.requires_module and not tpl.reuse_previous_module:
        c.module_id = mod.id  # remembered for round 2
    audit(db, user, "interview_booked", f"{tpl.name} on {fmt_date(start)} at {fmt_time(start)}", c.id)
    db.commit()
    return {"interview": row(iv)}


# ---------------------------------------------------------------- reschedule / cancel

class ReschedIn(BaseModel):
    start: str
    notify_candidate: bool = True


@router.post("/{iid}/reschedule")
def reschedule(iid: int, body: ReschedIn, user=Depends(require("interviews.schedule")), db: Session = Depends(get_db)):
    iv = get_or_404(db, models.Interview, iid, "Interview")
    c = check_visible(db, user, iv.candidate_id)
    if iv.status == "cancelled":
        raise HTTPException(400, "This interview was cancelled")
    if not iv.outlook_entry_id:
        raise HTTPException(400, "The original invite hasn't been created in Outlook yet (check the Outbox)")
    if iv.organizer_id and iv.organizer_id != user.id:
        org = db.get(models.User, iv.organizer_id)
        raise HTTPException(400, f"Only the organizer ({org.name if org else 'unknown'}) can move this Outlook invite")
    dur = iv.end - iv.start
    start = datetime.fromisoformat(body.start)
    iv.start, iv.end = start, start + dur
    queue_job(db, user, "update_appointment", {
        "entry_id": iv.outlook_entry_id, "start": iv.start.isoformat(), "end": iv.end.isoformat(),
    }, f"Reschedule: {iv.title}", c.id, iv.id)
    if body.notify_candidate:
        tpl = db.query(models.EmailTemplate).filter_by(key="reschedule").first()
        if tpl and tpl.active:
            mail = build_template_email(db, tpl, c, user, {
                "interview_date": fmt_date(start), "interview_time": fmt_time(start), "location": iv.location})
            mail["cc"] = join_emails(minus(split_emails(iv.required) + split_emails(iv.optional), [c.email, user.email]))
            queue_mail(db, user, mail, f"Reschedule notice: {c.first_name} {c.last_name}", c.id, iv.id)
    audit(db, user, "interview_rescheduled", f"{iv.title} to {fmt_date(start)} at {fmt_time(start)}", c.id)
    db.commit()
    return {"interview": row(iv)}


@router.post("/{iid}/cancel")
def cancel(iid: int, notify: bool = True, user=Depends(require("interviews.schedule")), db: Session = Depends(get_db)):
    iv = get_or_404(db, models.Interview, iid, "Interview")
    c = check_visible(db, user, iv.candidate_id)
    iv.status = "cancelled"
    if iv.outlook_entry_id and notify:
        queue_job(db, user, "cancel_appointment", {"entry_id": iv.outlook_entry_id},
                  f"Cancel: {iv.title}", c.id, iv.id)
    for a in db.query(models.TestAssignment).filter_by(interview_id=iv.id, status="assigned"):
        a.status = "revoked"
    audit(db, user, "interview_cancelled", iv.title, c.id)
    db.commit()
    return {"ok": True}
