"""Clearing out old candidate data.

Rejected and Withdrawn candidates have their personal details removed a set number of months after they reached that
stage. Admins are warned first, and a candidate is only cleared once the warning is at least `retention_warn_days` old.
What's left (department, stage, dates, source, position, decision) keeps reports and counts working."""
import os
import shutil
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models
from .perms import has
from .services import audit, get_setting, set_setting, notify, local_now

CLEARED_FIELDS = ("email", "phone", "resume_link", "ai_interview_link", "notes", "location", "screening_result",
                  "screening_comments", "oracle_experience", "area_fit", "ribbon_rating", "round1_info", "round2_info",
                  "interviewer", "interviewer_comment")


def enabled(db: Session) -> bool:
    return get_setting(db, "retention_enabled") == "true"


def months(db: Session) -> int:
    return max(1, int(get_setting(db, "retention_months") or 12))


def warn_days(db: Session) -> int:
    return max(1, int(get_setting(db, "retention_warn_days") or 14))


def clear_after(c: models.Candidate, m: int) -> datetime:
    return (c.stage_changed_at or c.updated_at or datetime.utcnow()) + timedelta(days=round(m * 30.44))


def closed_stage_ids(db: Session) -> list[int]:
    return [s.id for s in db.query(models.Stage).filter(models.Stage.kind.in_(["rejected", "withdrawn"]))]


def upcoming(db: Session, within_days: int | None = None) -> list[tuple[models.Candidate, datetime]]:
    """Candidates that will be cleared, with the earliest date it can happen."""
    m, w = months(db), warn_days(db)
    now = datetime.utcnow()
    horizon = now + timedelta(days=within_days if within_days is not None else w)
    out = []
    q = db.query(models.Candidate).filter(models.Candidate.stage_id.in_(closed_stage_ids(db)),
                                          models.Candidate.anonymized_at.is_(None), models.Candidate.retention_keep.is_(False))
    for c in q:
        due = clear_after(c, m)
        if c.retention_warned_at:
            due = max(due, c.retention_warned_at + timedelta(days=w))
        else:
            due = max(due, now + timedelta(days=w))  # not warned yet: the warning goes out first
        if due <= horizon:
            out.append((c, due))
    return sorted(out, key=lambda x: x[1])


def anonymize(db: Session, c: models.Candidate, actor: models.User | None = None):
    from .recsvc import remove_assignment_files
    from .mailbox import delete_files
    label = f"#{c.id}"
    for f in CLEARED_FIELDS:
        setattr(c, f, "")
    c.first_name, c.last_name = "Removed candidate", label
    c.custom, c.fields = {}, {}
    c.anonymized_at = datetime.utcnow()
    # emails and replies the candidate sent, with attachments
    mails = db.query(models.CandidateEmail).filter_by(candidate_id=c.id).all()
    delete_files([m.id for m in mails])
    for m in mails:
        db.delete(m)
    # test answers and uploaded files; scores stay for reports
    for a in db.query(models.TestAssignment).filter_by(candidate_id=c.id):
        remove_assignment_files(a.id)
        db.query(models.Answer).filter_by(assignment_id=a.id).delete()
        a.username = f"removed-{a.id}"
        a.events, a.reviewer_notes, a.session_id = [], "", None
    # interview invites carried names and addresses
    for iv in db.query(models.Interview).filter_by(candidate_id=c.id):
        iv.title, iv.required, iv.optional, iv.body, iv.location = f"Interview, round {iv.round_number}", "", "", "", ""
    db.query(models.Feedback).filter_by(candidate_id=c.id).delete()
    for j in db.query(models.OutboxJob).filter_by(candidate_id=c.id):
        j.payload, j.result, j.description = {}, None, f"Message to removed candidate {label}"
    for row in db.query(models.AuditLog).filter_by(candidate_id=c.id):
        row.detail = ""
    db.query(models.Notification).filter(models.Notification.link == f"/candidates/{c.id}").delete()
    audit(db, actor, "candidate_data_cleared", f"Personal details removed after {months(db)} months", candidate_id=c.id)


def due_now(db: Session) -> bool:
    return enabled(db) and get_setting(db, "retention_last_run") != local_now().date().isoformat()


def run(db: Session) -> dict:
    """Once a day: warn admins about the next batch, clear candidates whose warning period has passed."""
    set_setting(db, "retention_last_run", local_now().date().isoformat())
    if not enabled(db):
        db.commit()
        return {"warned": 0, "cleared": 0}
    m, w = months(db), warn_days(db)
    now = datetime.utcnow()
    to_warn, cleared = [], 0
    q = db.query(models.Candidate).filter(models.Candidate.stage_id.in_(closed_stage_ids(db)),
                                          models.Candidate.anonymized_at.is_(None), models.Candidate.retention_keep.is_(False))
    for c in q.all():
        if clear_after(c, m) - timedelta(days=w) > now:
            continue
        if not c.retention_warned_at:
            c.retention_warned_at = now
            to_warn.append(c)
        elif c.retention_warned_at + timedelta(days=w) <= now and clear_after(c, m) <= now:
            anonymize(db, c)
            cleared += 1
    if to_warn:
        on = (now + timedelta(days=w)).date().isoformat()
        for u in db.query(models.User).filter(models.User.active.is_(True)):
            if has(u, "users.manage"):
                notify(db, "retention", f"{len(to_warn)} candidate(s) will have their details removed from {on}",
                       "Rejected or withdrawn long enough ago. Tick Keep on anyone you need to hold on to.",
                       "/settings?tab=retention", user_id=u.id)
    if cleared:
        audit(db, None, "retention_run", f"{cleared} candidate(s) cleared")
    db.commit()
    return {"warned": len(to_warn), "cleared": cleared}
