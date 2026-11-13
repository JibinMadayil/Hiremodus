"""Optional interview feedback: a short form per interview, per interviewer. Questions are edited in Settings."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..perms import require, candidate_access, has
from ..services import audit
from ..util import row

router = APIRouter(tags=["feedback"])
KINDS = ("rating", "choice", "text")


def questions(db, active_only=True):
    q = db.query(models.FeedbackQuestion)
    if active_only:
        q = q.filter(models.FeedbackQuestion.active.is_(True))
    return q.order_by(models.FeedbackQuestion.sort, models.FeedbackQuestion.id).all()


def feedback_for(db, candidate_id: int) -> list[dict]:
    names = {u.id: u.name for u in db.query(models.User)}
    return [dict(row(f), user_name=names.get(f.user_id, "Former user"))
            for f in db.query(models.Feedback).filter_by(candidate_id=candidate_id).order_by(models.Feedback.created_at)]


@router.get("/api/feedback/questions")
def list_questions(all: bool = False, user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    return [row(q) for q in questions(db, active_only=not all)]


class QIn(BaseModel):
    label: str
    kind: str = "text"
    options: list[str] = []
    required: bool = False
    active: bool = True
    sort: int = 0


def _check(body: QIn):
    if not body.label.strip():
        raise HTTPException(400, "Give the question a label")
    if body.kind not in KINDS:
        raise HTTPException(400, "Type must be rating, choice or text")
    if body.kind == "choice" and len([o for o in body.options if o.strip()]) < 2:
        raise HTTPException(400, "A choice question needs at least two options")


@router.post("/api/feedback/questions")
def add_question(body: QIn, user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    _check(body)
    q = models.FeedbackQuestion(label=body.label.strip(), kind=body.kind, required=body.required, active=body.active,
                                options=["1", "2", "3", "4", "5"] if body.kind == "rating" else [o.strip() for o in body.options if o.strip()],
                                sort=body.sort or (len(questions(db, False)) + 1))
    db.add(q)
    db.commit()
    return row(q)


@router.put("/api/feedback/questions/{qid}")
def edit_question(qid: int, body: QIn, user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    _check(body)
    q = db.get(models.FeedbackQuestion, qid)
    if not q:
        raise HTTPException(404, "Question not found")
    q.label, q.kind, q.required, q.active, q.sort = body.label.strip(), body.kind, body.required, body.active, body.sort
    q.options = ["1", "2", "3", "4", "5"] if body.kind == "rating" else [o.strip() for o in body.options if o.strip()]
    db.commit()
    return row(q)


@router.delete("/api/feedback/questions/{qid}")
def delete_question(qid: int, user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    q = db.get(models.FeedbackQuestion, qid)
    if not q:
        raise HTTPException(404, "Question not found")
    used = any(str(qid) in (f.answers or {}) for f in db.query(models.Feedback))
    if used:
        q.active = False  # keep it so old feedback still reads correctly
    else:
        db.delete(q)
    db.commit()
    return {"ok": True, "hidden_instead": used}


class FbIn(BaseModel):
    answers: dict


def _interview(db, user, iid):
    iv = db.get(models.Interview, iid)
    if not iv:
        raise HTTPException(404, "Interview not found")
    c = db.get(models.Candidate, iv.candidate_id)
    if not c or candidate_access(db, user, c) != "full":
        raise HTTPException(403, "This candidate belongs to a department you don't work in")
    return iv, c


@router.post("/api/interviews/{iid}/feedback")
def save_feedback(iid: int, body: FbIn, user=Depends(require("candidates.edit")), db: Session = Depends(get_db)):
    iv, c = _interview(db, user, iid)
    if iv.status == "cancelled":
        raise HTTPException(400, "This interview was cancelled")
    clean = {}
    for q in questions(db):
        v = body.answers.get(str(q.id))
        v = "" if v is None else str(v).strip()
        if q.required and not v:
            raise HTTPException(400, f"'{q.label}' is required")
        if v and q.kind in ("rating", "choice") and v not in q.options:
            raise HTTPException(400, f"'{q.label}': pick one of {', '.join(q.options)}")
        if v:
            clean[str(q.id)] = v[:5000]
    f = db.query(models.Feedback).filter_by(interview_id=iv.id, user_id=user.id).first()
    if f:
        f.answers, f.updated_at = clean, datetime.utcnow()
    else:
        f = models.Feedback(interview_id=iv.id, candidate_id=c.id, user_id=user.id, answers=clean)
        db.add(f)
    audit(db, user, "feedback_saved", iv.title or f"Round {iv.round_number}", candidate_id=c.id)
    db.commit()
    return row(f)


@router.delete("/api/feedback/{fid}")
def delete_feedback(fid: int, user=Depends(require("candidates.edit")), db: Session = Depends(get_db)):
    f = db.get(models.Feedback, fid)
    if not f:
        raise HTTPException(404, "Feedback not found")
    if f.user_id != user.id and not has(user, "users.manage"):
        raise HTTPException(403, "You can only remove your own feedback")
    db.delete(f)
    audit(db, user, "feedback_removed", "", candidate_id=f.candidate_id)
    db.commit()
    return {"ok": True}
