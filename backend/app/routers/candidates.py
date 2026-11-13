from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..mailbox import unread_counts, email_out
from .feedback import feedback_for
from ..perms import require, dept_scope, has, candidate_access, associate_only
from ..services import (audit, build_template_email, queue_mail, queue_it_notice, clean_email, get_setting,
                        candidate_context, render, join_emails, split_emails, local_now, change_stage, notify)
from ..util import row, rows, get_or_404, apply
from ..aging import cfg as aging_cfg, evaluate as aging_eval, interviews_by_candidate, reset_clock

router = APIRouter(prefix="/api/candidates", tags=["candidates"])

EDITABLE = {"first_name", "last_name", "email", "phone", "resume_link", "position", "source",
            "ai_interview_link", "department_id", "module_id", "notes", "custom", "location", "screening_result",
            "screening_comments", "oracle_experience", "area_fit", "ribbon_rating", "round1_info", "round2_info",
            "test_score", "interviewer", "interviewer_comment", "practice", "final_decision", "date_added"}
INTERVIEWER_EDITABLE = {"notes", "interviewer_comment", "test_score", "interviewer"}
EDITABLE = EDITABLE | {"fields"}


SUMMARY_FIELDS = {"id", "first_name", "last_name", "stage_id", "department_id", "aging", "next_interview",
                  "date_added", "created_at", "access", "transfer", "duplicate", "location"}


def visible_query(db: Session, user: models.User):
    return db.query(models.Candidate)


def check_visible(db: Session, user: models.User, cid: int) -> models.Candidate:
    c = get_or_404(db, models.Candidate, cid, "Candidate")
    if candidate_access(db, user, c) != "full":
        raise HTTPException(403, "This candidate belongs to another department. You can see where they are, but not open their details.")
    return c


def pending_transfers(db: Session, ids: list[int] | None = None) -> dict[int, models.Transfer]:
    q = db.query(models.Transfer).filter(models.Transfer.status == "pending")
    if ids is not None:
        q = q.filter(models.Transfer.candidate_id.in_(ids or [-1]))
    return {t.candidate_id: t for t in q}


def transfer_out(t: models.Transfer | None, depts: dict, users: dict | None = None) -> dict | None:
    if not t:
        return None
    return {"id": t.id, "from_department_id": t.from_department_id, "to_department_id": t.to_department_id,
            "from": depts.get(t.from_department_id, ""), "to": depts.get(t.to_department_id, ""), "note": t.note,
            "requested_by": t.requested_by, "requested_by_name": (users or {}).get(t.requested_by, ""),
            "requested_at": t.requested_at.isoformat() + "Z", "status": t.status}


def duplicate_emails(db: Session) -> set[str]:
    rows_ = (db.query(func.lower(models.Candidate.email)).filter(models.Candidate.email != "")
             .group_by(func.lower(models.Candidate.email)).having(func.count() > 1).all())
    return {r[0] for r in rows_}


def cand_out(c: models.Candidate, dups: set[str]) -> dict:
    d = row(c)
    d["duplicate"] = (c.email or "").lower() in dups
    return d


@router.get("")
def list_candidates(stage_id: int | None = None, department_id: int | None = None, q: str = "",
                    duplicates_only: bool = False, aging: str = "", mine: bool = False, unread_only: bool = False, user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    query = visible_query(db, user)
    if stage_id:
        query = query.filter(models.Candidate.stage_id == stage_id)
    if department_id:
        query = query.filter(models.Candidate.department_id == department_id)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(models.Candidate.first_name.ilike(like), models.Candidate.last_name.ilike(like),
                                 models.Candidate.email.ilike(like), models.Candidate.phone.ilike(like),
                                 models.Candidate.position.ilike(like)))
    dups = duplicate_emails(db)
    items = query.order_by(models.Candidate.updated_at.desc()).limit(5000).all()
    out = [cand_out(c, dups) for c in items]
    conf = aging_cfg(db)
    stages = {st.id: st for st in db.query(models.Stage)}
    ivs = interviews_by_candidate(db, [c.id for c in items])
    now_local = local_now()
    scope = dept_scope(user)
    pend_all = pending_transfers(db, [c.id for c in items])
    in_scope_pending = {cid for cid, t in pend_all.items() if scope is not None and t.to_department_id in scope}
    dnames = {d.id: d.name for d in db.query(models.Department)}
    for c, d in zip(items, out):
        d["aging"] = aging_eval(c, stages.get(c.stage_id), ivs.get(c.id, []), conf, now_local)
        d["access"] = candidate_access(db, user, c, scope, in_scope_pending)
        d["transfer"] = transfer_out(pend_all.get(c.id), dnames)
    if mine:
        # yours = your departments, plus candidates nobody owns yet who are still in an active stage (AI stages, Screening)
        out = [d for d in out if d["access"] == "full" and (d.get("department_id") or (stages.get(d.get("stage_id")) and stages[d["stage_id"]].kind == "open"))]
    out = [d if d["access"] == "full" else {k: v for k, v in d.items() if k in SUMMARY_FIELDS} for d in out]
    if duplicates_only:
        out = [c for c in out if c["duplicate"]]
    if aging == "over":
        out = [c for c in out if c["aging"] and c["aging"]["status"] in ("alert", "due", "grace")]
    elif aging == "due":
        out = [c for c in out if c["aging"] and c["aging"]["status"] in ("due", "grace")]
    # next interview per candidate, for the list view
    ids = [c["id"] for c in out]
    if ids:
        nxt = {}
        for iv in (db.query(models.Interview).filter(models.Interview.candidate_id.in_(ids),
                                                     models.Interview.status.in_(["sending", "scheduled"]),
                                                     models.Interview.start >= local_now().replace(hour=0, minute=0))
                   .order_by(models.Interview.start)):
            nxt.setdefault(iv.candidate_id, iv.start.isoformat())
        unread = unread_counts(db, user, [c["id"] for c in out if c.get("access") == "full"])
        for c in out:
            c["next_interview"] = nxt.get(c["id"])
            if c.get("access") == "full":
                c["unread_replies"] = unread.get(c["id"], 0)
    if unread_only:
        out = [c for c in out if c.get("unread_replies")]
    return out


class CandIn(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    resume_link: str = ""
    position: str = ""
    source: str = ""
    location: str = ""
    screening_result: str = ""
    screening_comments: str = ""
    oracle_experience: str = ""
    ribbon_rating: str = ""
    ai_interview_link: str = ""
    department_id: int | None = None
    stage_id: int | None = None
    module_id: int | None = None
    notes: str = ""


@router.post("")
def create_candidate(body: CandIn, user=Depends(require("candidates.edit")), db: Session = Depends(get_db)):
    data = body.model_dump()
    data["email"] = clean_email(data["email"])
    if not data["first_name"] and not data["last_name"]:
        raise HTTPException(400, "Enter at least a first or last name")
    if associate_only(user) and data.get("stage_id"):
        st = db.get(models.Stage, data["stage_id"])
        if st and st.kind == "open" and st.requires_department:
            raise HTTPException(403, "Associates add candidates to the AI stages or Screening")
    c = models.Candidate()
    apply(c, data)
    if not c.stage_id:
        first = db.query(models.Stage).filter(models.Stage.active).order_by(models.Stage.sort).first()
        c.stage_id = first.id if first else None
    c.clock_started_at = datetime.utcnow()
    db.add(c)
    db.flush()
    audit(db, user, "candidate_created", f"{c.first_name} {c.last_name}", c.id)
    existing = 0
    if c.email:
        existing = db.query(models.Candidate).filter(func.lower(models.Candidate.email) == c.email,
                                                     models.Candidate.id != c.id).count()
    db.commit()
    return {"candidate": row(c), "duplicate_of": existing}


@router.get("/search")
def quick_search(q: str = "", user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    """Fast lookup for the search box: no aging maths, at most 10 rows."""
    t = q.strip()
    if len(t) < 2:
        return []
    like = f"%{t}%"
    parts = t.split()
    cond = or_(models.Candidate.first_name.ilike(like), models.Candidate.last_name.ilike(like),
               models.Candidate.email.ilike(like), models.Candidate.phone.ilike(like))
    if len(parts) >= 2:
        cond = or_(cond, (models.Candidate.first_name.ilike(f"%{parts[0]}%") & models.Candidate.last_name.ilike(f"%{parts[-1]}%")))
    rows_ = db.query(models.Candidate).filter(cond).order_by(models.Candidate.updated_at.desc()).limit(10).all()
    scope = dept_scope(user)
    out = []
    for c in rows_:
        acc = candidate_access(db, user, c, scope)
        out.append({"id": c.id, "first_name": c.first_name, "last_name": c.last_name, "stage_id": c.stage_id,
                    "department_id": c.department_id, "access": acc, "email": c.email if acc == "full" else ""})
    return out


@router.get("/{cid}")
def get_candidate(cid: int, user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    c = get_or_404(db, models.Candidate, cid, "Candidate")
    dnames = {d.id: d.name for d in db.query(models.Department)}
    unames = {u.id: u.name for u in db.query(models.User)}
    pend = pending_transfers(db, [c.id]).get(c.id)
    if candidate_access(db, user, c) != "full":
        d = cand_out(c, set())
        d["aging"] = aging_eval(c, db.get(models.Stage, c.stage_id) if c.stage_id else None,
                                interviews_by_candidate(db, [c.id]).get(c.id, []), aging_cfg(db))
        d["access"] = "summary"
        d["transfer"] = transfer_out(pend, dnames, unames)
        d["feedback_count"] = db.query(models.Feedback).filter_by(candidate_id=c.id).count()
        return {"candidate": {k: v for k, v in d.items() if k in SUMMARY_FIELDS | {"feedback_count"}}, "access": "summary",
                "same_email": [], "interviews": [], "assignments": [], "jobs": [], "log": [], "transfers": []}
    dups = duplicate_emails(db)
    others = []
    if c.email:
        others = [{"id": o.id, "stage_id": o.stage_id, "department_id": o.department_id, "name": f"{o.first_name} {o.last_name}"}
                  for o in db.query(models.Candidate).filter(func.lower(models.Candidate.email) == c.email.lower(),
                                                             models.Candidate.id != c.id)]
    interviews = db.query(models.Interview).filter_by(candidate_id=c.id).order_by(models.Interview.start.desc()).all()
    assignments = db.query(models.TestAssignment).filter_by(candidate_id=c.id).order_by(models.TestAssignment.created_at.desc()).all()
    jobs = db.query(models.OutboxJob).filter_by(candidate_id=c.id).order_by(models.OutboxJob.created_at.desc()).limit(100).all()
    log = db.query(models.AuditLog).filter_by(candidate_id=c.id).order_by(models.AuditLog.at.desc()).limit(200).all()
    tests = {t.id: t.name for t in db.query(models.Test).all()}
    a_out = []
    for a in assignments:
        d = row(a, {"password_hash", "code_hash"})
        d["test_name"] = tests.get(a.test_id, "")
        d["code_active"] = bool(a.code_expires and a.code_expires > datetime.utcnow() and a.code_hash)
        a_out.append(d)
    cd = cand_out(c, dups)
    cd["aging"] = aging_eval(c, db.get(models.Stage, c.stage_id) if c.stage_id else None,
                             interviews_by_candidate(db, [c.id]).get(c.id, []), aging_cfg(db))
    lc = db.get(models.User, c.last_contact_by) if c.last_contact_by else None
    cd["last_contact_name"] = lc.name if lc else ""
    cd["access"] = "full"
    cd["transfer"] = transfer_out(pend, dnames, unames)
    history = [transfer_out(t, dnames, unames) | {"decided_by_name": unames.get(t.decided_by, ""), "decision_note": t.decision_note,
                                                  "decided_at": t.decided_at.isoformat() + "Z" if t.decided_at else None}
               for t in db.query(models.Transfer).filter_by(candidate_id=c.id).order_by(models.Transfer.requested_at.desc())]
    return {
        "access": "full",
        "transfers": history,
        "candidate": cd,
        "same_email": others,
        "interviews": rows(interviews),
        "assignments": a_out,
        "jobs": [dict(row(j, {"payload", "result"}), subject=(j.payload or {}).get("subject", ""),
                      reply_to=(j.payload or {}).get("reply_to"), threaded=(j.result or {}).get("threaded")) for j in jobs],
        "feedback": feedback_for(db, c.id),
        "emails": [email_out(e, user) for e in db.query(models.CandidateEmail).filter_by(candidate_id=c.id)
                   .order_by(models.CandidateEmail.received_at.desc()).limit(200)],
        "log": rows(log),
    }


@router.patch("/{cid}")
def update_candidate(cid: int, body: dict, user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    c = check_visible(db, user, cid)
    allowed = set(EDITABLE if has(user, "candidates.edit") else INTERVIEWER_EDITABLE)
    if not has(user, "candidates.edit_date_added"):
        allowed.discard("date_added")
        if "date_added" in body:
            raise HTTPException(403, "Only users allowed to change Date added can edit it")
    if "email" in body:
        body["email"] = clean_email(body["email"])
    if "department_id" in body and body["department_id"] != c.department_id:
        if body["department_id"] and needs_transfer(user, c, body["department_id"]):
            raise HTTPException(400, "That department isn't yours. Use Transfer and add a note for them.")
        if associate_only(user) and c.department_id:
            raise HTTPException(403, "This candidate already belongs to a department")
    before_link = c.ai_interview_link
    apply(c, body, allowed)
    msgs = []
    # pasting the AI interview result link moves the candidate to the configured next stage
    if c.ai_interview_link and c.ai_interview_link != before_link and c.stage_id:
        st = db.get(models.Stage, c.stage_id)
        prefix = get_setting(db, "ai_link_prefix").strip().lower()
        if st and st.advance_on_ai_link_to_id and (not prefix or c.ai_interview_link.lower().startswith(prefix)):
            change_stage(db, c, st.advance_on_ai_link_to_id, user)
            nxt = db.get(models.Stage, c.stage_id)
            msgs.append(f"AI interview link added, moved to {nxt.name if nxt else 'next stage'}")
    audit(db, user, "candidate_updated", ", ".join(k for k in body if k in allowed), c.id)
    db.commit()
    return {"candidate": row(c), "messages": msgs}


@router.delete("/{cid}")
def delete_candidate(cid: int, user=Depends(require("candidates.delete")), db: Session = Depends(get_db)):
    c = get_or_404(db, models.Candidate, cid, "Candidate")
    audit(db, user, "candidate_deleted", f"{c.first_name} {c.last_name} <{c.email}>")
    from ..recsvc import remove_assignment_files
    for a in db.query(models.TestAssignment).filter_by(candidate_id=c.id):
        remove_assignment_files(a.id)
    from ..mailbox import delete_files
    mails = db.query(models.CandidateEmail).filter_by(candidate_id=c.id).all()
    delete_files([m.id for m in mails])
    for m in mails:
        db.delete(m)
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- moving between stages

class MoveIn(BaseModel):
    ids: list[int]
    stage_id: int | None = None
    department_id: int | None = None
    send_email: bool = True
    note: str = ""  # required when the move is a transfer to a department the user doesn't work in


def needs_transfer(user, c: models.Candidate, department_id) -> bool:
    scope = dept_scope(user)
    return bool(scope is not None and department_id and c.department_id and department_id != c.department_id
                and department_id not in scope)


def request_transfer(db, user, c: models.Candidate, to_dept: int, note: str) -> models.Transfer:
    if not note.strip():
        raise HTTPException(400, "Add a note saying why you're transferring this candidate")
    for old in db.query(models.Transfer).filter_by(candidate_id=c.id, status="pending"):
        old.status = "cancelled"
    t = models.Transfer(candidate_id=c.id, from_department_id=c.department_id, to_department_id=to_dept,
                        note=note.strip(), requested_by=user.id)
    db.add(t)
    db.flush()
    dnames = {d.id: d.name for d in db.query(models.Department)}
    name = f"{c.first_name} {c.last_name}".strip()
    audit(db, user, "transfer_requested", f"{dnames.get(c.department_id, '')} → {dnames.get(to_dept, '')}: {note.strip()}", c.id)
    for u in transfer_recipients(db, to_dept):
        notify(db, "transfer", f"Transfer request: {name} from {dnames.get(c.department_id, '')}",
               f"{user.name}: {note.strip()}", f"/candidates/{c.id}", user_id=u.id)
    return t


def transfer_recipients(db, dept_id: int) -> list[models.User]:
    out = []
    for u in db.query(models.User).filter(models.User.active.is_(True)):
        scope = dept_scope(u)
        if scope is not None and dept_id in scope and has(u, "candidates.edit"):
            out.append(u)
    if not out:  # nobody works in that department yet: tell the admins
        out = [u for u in db.query(models.User).filter(models.User.active.is_(True)) if has(u, "users.manage")]
    return out


def move_one(db, user, c: models.Candidate, stage: models.Stage | None, department_id, send_email, note="") -> dict:
    res = {"id": c.id, "name": f"{c.first_name} {c.last_name}".strip(), "emailed": False, "error": "", "transferred": False}
    if stage and stage.kind == "hired" and not has(user, "candidates.hire"):
        res["error"] = "your role can't hire"
        return res
    if stage and stage.kind == "open" and stage.requires_department and associate_only(user):
        res["error"] = "associates hand candidates off to a department; the department moves them on from there"
        return res
    if department_id is not None and needs_transfer(user, c, department_id):
        if not note.strip():
            res["error"] = "needs a transfer note"
            return res
        request_transfer(db, user, c, department_id, note)
        res["transferred"] = True
        return res
    handoff = department_id is not None and department_id and not c.department_id
    if department_id is not None:
        c.department_id = department_id or None
    if handoff:
        dname = db.get(models.Department, department_id).name
        for u in transfer_recipients(db, department_id):
            if u.id != user.id:
                notify(db, "handoff", f"New candidate for {dname}: {res['name']}", f"Handed over by {user.name}",
                       f"/candidates/{c.id}", user_id=u.id)
    if stage:
        if stage.requires_department and not c.department_id:
            res["error"] = "needs a department first"
            return res
        change_stage(db, c, stage.id, user)
        if send_email and stage.entry_template_id:
            tpl = db.get(models.EmailTemplate, stage.entry_template_id)
            if tpl and tpl.active:
                if not c.email:
                    res["error"] = "no email on file, not emailed"
                else:
                    mail = build_template_email(db, tpl, c, user)
                    queue_mail(db, user, mail, f"{tpl.name}: {res['name']}", c.id)
                    res["emailed"] = True
    dept = db.get(models.Department, c.department_id) if c.department_id else None
    audit(db, user, "moved", f"{stage.name if stage else ''}{' / ' + dept.name if dept else ''}"
          f"{' (email queued)' if res['emailed'] else ''}", c.id)
    return res


@router.post("/bulk/move")
def bulk_move(body: MoveIn, user=Depends(require("candidates.edit")), db: Session = Depends(get_db)):
    stage = db.get(models.Stage, body.stage_id) if body.stage_id else None
    out = []
    for cid in body.ids:
        c = db.get(models.Candidate, cid)
        if c:
            if candidate_access(db, user, c) != "full":
                out.append({"id": c.id, "name": f"{c.first_name} {c.last_name}".strip(), "error": "belongs to another department", "emailed": False})
                continue
            out.append(move_one(db, user, c, stage, body.department_id, body.send_email, body.note))
    db.commit()
    return {"results": out}


# ---------------------------------------------------------------- template emails

class EmailIn(BaseModel):
    template_id: int
    subject: str | None = None
    body: str | None = None
    cc: str | None = None


@router.post("/{cid}/email/preview")
def email_preview(cid: int, body: EmailIn, user=Depends(require("emails.send")), db: Session = Depends(get_db)):
    c = check_visible(db, user, cid)
    tpl = get_or_404(db, models.EmailTemplate, body.template_id, "Template")
    mail = build_template_email(db, tpl, c, user)
    stage = db.get(models.Stage, tpl.moves_to_stage_id) if tpl.moves_to_stage_id else None
    mail["moves_to"] = stage.name if stage else None
    mail["notify_it"] = bool(tpl.notify_it and tpl.it_links.strip())
    return mail


def send_template(db, user, c: models.Candidate, tpl: models.EmailTemplate, overrides: EmailIn | None = None):
    mail = build_template_email(db, tpl, c, user)
    if overrides:
        if overrides.subject is not None:
            mail["subject"] = overrides.subject
        if overrides.body is not None:
            mail["body"] = overrides.body
        if overrides.cc is not None:
            mail["cc"] = join_emails(overrides.cc)
    queue_mail(db, user, mail, f"{tpl.name}: {c.first_name} {c.last_name}", c.id)
    audit(db, user, "email_queued", tpl.name, c.id)
    if tpl.notify_it and tpl.it_links.strip():
        links = render(tpl.it_links, candidate_context(db, c, user))
        queue_it_notice(db, user, c, tpl.name, links)
    if tpl.moves_to_stage_id and c.stage_id != tpl.moves_to_stage_id:
        change_stage(db, c, tpl.moves_to_stage_id, user)


@router.post("/{cid}/email/send")
def email_send(cid: int, body: EmailIn, user=Depends(require("emails.send")), db: Session = Depends(get_db)):
    c = check_visible(db, user, cid)
    if not c.email:
        raise HTTPException(400, "This candidate has no email address")
    tpl = get_or_404(db, models.EmailTemplate, body.template_id, "Template")
    send_template(db, user, c, tpl, body)
    db.commit()
    return {"ok": True}


class BulkEmailIn(BaseModel):
    ids: list[int]
    template_id: int


@router.post("/bulk/email")
def bulk_email(body: BulkEmailIn, user=Depends(require("emails.send")), db: Session = Depends(get_db)):
    tpl = get_or_404(db, models.EmailTemplate, body.template_id, "Template")
    out = []
    for cid in body.ids:
        c = db.get(models.Candidate, cid)
        if not c:
            continue
        name = f"{c.first_name} {c.last_name}".strip()
        if candidate_access(db, user, c) != "full":
            out.append({"id": cid, "name": name, "ok": False, "error": "belongs to another department"})
            continue
        if not c.email:
            out.append({"id": cid, "name": name, "ok": False, "error": "no email on file"})
            continue
        send_template(db, user, c, tpl)
        out.append({"id": cid, "name": name, "ok": True})
    db.commit()
    return {"results": out}


@router.post("/{cid}/contacted")
def mark_contacted(cid: int, user=Depends(require("candidates.edit")), db: Session = Depends(get_db)):
    c = check_visible(db, user, cid)
    reset_clock(c, user)
    audit(db, user, "marked_contacted", "Aging clock restarted", c.id)
    db.commit()
    return {"ok": True}


class ExemptIn(BaseModel):
    exempt: bool


@router.post("/{cid}/aging-exempt")
def set_exempt(cid: int, body: ExemptIn, user=Depends(require("candidates.edit")), db: Session = Depends(get_db)):
    c = check_visible(db, user, cid)
    c.aging_exempt = body.exempt
    audit(db, user, "aging_keep_on" if body.exempt else "aging_keep_off",
          "Won't be auto-rejected" if body.exempt else "Aging rules apply again", c.id)
    db.commit()
    return {"ok": True}



# ---------------------------------------------------------------- transfers

class TransferIn(BaseModel):
    to_department_id: int
    note: str


@router.post("/{cid}/transfer")
def transfer(cid: int, body: TransferIn, user=Depends(require("candidates.edit")), db: Session = Depends(get_db)):
    c = check_visible(db, user, cid)
    if not c.department_id:
        raise HTTPException(400, "This candidate has no department yet. Assign one with Move instead.")
    if body.to_department_id == c.department_id:
        raise HTTPException(400, "The candidate is already in that department")
    get_or_404(db, models.Department, body.to_department_id, "Department")
    t = request_transfer(db, user, c, body.to_department_id, body.note)
    db.commit()
    return {"ok": True, "id": t.id}


def load_transfer(db, user, tid) -> tuple[models.Transfer, models.Candidate]:
    t = get_or_404(db, models.Transfer, tid, "Transfer")
    if t.status != "pending":
        raise HTTPException(400, f"This transfer was already {t.status}")
    return t, get_or_404(db, models.Candidate, t.candidate_id, "Candidate")


def can_decide(user, t: models.Transfer) -> bool:
    scope = dept_scope(user)
    return has(user, "candidates.edit") and (scope is None or t.to_department_id in scope)


@router.post("/transfers/{tid}/accept")
def accept_transfer(tid: int, user=Depends(require("candidates.edit")), db: Session = Depends(get_db)):
    t, c = load_transfer(db, user, tid)
    if not can_decide(user, t):
        raise HTTPException(403, "Only the receiving department can accept this")
    dnames = {d.id: d.name for d in db.query(models.Department)}
    c.department_id = t.to_department_id
    t.status, t.decided_by, t.decided_at = "accepted", user.id, datetime.utcnow()
    name = f"{c.first_name} {c.last_name}".strip()
    audit(db, user, "transfer_accepted", f"Now in {dnames.get(t.to_department_id, '')}", c.id)
    if t.requested_by:
        notify(db, "transfer", f"{dnames.get(t.to_department_id, '')} accepted {name}", "", f"/candidates/{c.id}", user_id=t.requested_by)
    db.commit()
    return {"ok": True}


class DeclineIn(BaseModel):
    note: str = ""
    send_email: bool = True


@router.post("/transfers/{tid}/decline")
def decline_transfer(tid: int, body: DeclineIn, user=Depends(require("candidates.edit")), db: Session = Depends(get_db)):
    t, c = load_transfer(db, user, tid)
    if not can_decide(user, t):
        raise HTTPException(403, "Only the receiving department can decline this")
    dnames = {d.id: d.name for d in db.query(models.Department)}
    t.status, t.decided_by, t.decided_at, t.decision_note = "declined", user.id, datetime.utcnow(), body.note.strip()
    reject = db.query(models.Stage).filter(models.Stage.kind == "rejected", models.Stage.active.is_(True)).order_by(models.Stage.sort).first()
    res = move_one(db, user, c, reject, None, body.send_email) if reject else {}
    name = f"{c.first_name} {c.last_name}".strip()
    audit(db, user, "transfer_declined", f"{dnames.get(t.to_department_id, '')} declined{': ' + body.note.strip() if body.note.strip() else ''}. Candidate rejected.", c.id)
    if t.requested_by:
        notify(db, "transfer", f"{dnames.get(t.to_department_id, '')} declined {name}; candidate rejected",
               body.note.strip(), f"/candidates/{c.id}", user_id=t.requested_by)
    db.commit()
    return {"ok": True, "emailed": res.get("emailed", False)}


@router.post("/transfers/{tid}/cancel")
def cancel_transfer(tid: int, user=Depends(require("candidates.edit")), db: Session = Depends(get_db)):
    t, c = load_transfer(db, user, tid)
    if t.requested_by != user.id and not has(user, "users.manage"):
        raise HTTPException(403, "Only the person who asked can cancel")
    t.status, t.decided_by, t.decided_at = "cancelled", user.id, datetime.utcnow()
    audit(db, user, "transfer_cancelled", "", c.id)
    db.commit()
    return {"ok": True}
