import re
from datetime import datetime

from sqlalchemy.orm import Session

from . import models
from .security import hash_password, random_password
from .services import get_setting


def make_username(db: Session, c: models.Candidate) -> str:
    base = re.sub(r"[^a-z0-9]", "", (c.first_name or "cand").lower())[:12] or "cand"
    last = re.sub(r"[^a-z0-9]", "", (c.last_name or "").lower())[:1]
    base = f"{base}{last}"
    n = 0
    while True:
        n += 1
        candidate = f"{base}{c.id}{'' if n == 1 else n}"
        if not db.query(models.TestAssignment).filter_by(username=candidate).first():
            return candidate


def create_assignment(db: Session, c: models.Candidate, test: models.Test,
                      interview_id: int | None = None) -> tuple[models.TestAssignment, str]:
    pw = random_password()
    a = models.TestAssignment(candidate_id=c.id, test_id=test.id, interview_id=interview_id,
                              username=make_username(db, c), password_hash=hash_password(pw))
    db.add(a)
    db.flush()
    return a, pw


def test_block(db: Session, a: models.TestAssignment, password: str, test: models.Test) -> str:
    url = get_setting(db, "portal_base_url")
    return (
        f"Assessment: {test.name} ({test.duration_min} minutes)\n"
        f"Test portal: {url}\n"
        f"Username: {a.username}\n"
        f"Password: {password}\n"
        "On the day of your interview, sign in to the test portal on your laptop. "
        "Your interviewer will give you a start code; the test begins when you enter it. "
        "The test runs in full screen and the timer cannot be paused."
    )


def test_ctx(db: Session, a: models.TestAssignment, password: str, test: models.Test) -> dict:
    return {
        "test_block": test_block(db, a, password, test),
        "test_name": test.name,
        "test_username": a.username,
        "test_password": password,
        "test_portal_url": get_setting(db, "portal_base_url"),
    }


def grade_auto(db: Session, a: models.TestAssignment):
    test = db.get(models.Test, a.test_id)
    answers = {x.question_id: x for x in db.query(models.Answer).filter_by(assignment_id=a.id)}
    auto, total = 0.0, 0.0
    drawn = set(a.question_order or [q.id for q in test.questions])
    for q in [q for q in test.questions if q.id in drawn]:
        total += q.points or 0
        ans = answers.get(q.id)
        if q.kind in ("mcq", "multi"):
            if q.kind == "mcq":
                correct = ans is not None and ans.value != "" and q.correct_index is not None \
                    and str(q.correct_index) == ans.value
            else:
                picked = sorted(int(x) for x in (ans.value.split(",") if ans and ans.value else []) if x.isdigit())
                correct = bool(q.correct_indices) and picked == sorted(q.correct_indices)
            pts = (q.points or 0) if correct else 0.0
            auto += pts
            if ans is None:
                ans = models.Answer(assignment_id=a.id, question_id=q.id, value="")
                db.add(ans)
            ans.score = pts
    a.auto_score = auto
    a.total_points = total


def finish(db: Session, a: models.TestAssignment, auto: bool = False):
    if a.status != "in_progress":
        return
    a.status = "submitted"
    a.submitted_at = datetime.utcnow()
    a.auto_submitted = auto
    a.code_hash = None
    grade_auto(db, a)
    notify_submitted(db, a, auto)


def notify_submitted(db: Session, a: models.TestAssignment, auto: bool):
    from .services import notify, queue_mail, split_emails, join_emails
    c = db.get(models.Candidate, a.candidate_id)
    test = db.get(models.Test, a.test_id)
    name = f"{c.first_name} {c.last_name}".strip() if c else "A candidate"
    title = f"{name} submitted {test.name}" + (" (time ran out)" if auto else "")
    if get_setting(db, "notify_test_submitted_inapp") == "true":
        notify(db, "test_submitted", title, f"Score so far: {a.auto_score or 0:g} / {a.total_points or 0:g} (written answers still to grade)",
               f"/results/{a.id}", permission="tests.results")
    emails = split_emails(get_setting(db, "notify_test_submitted_emails"))
    sender = db.query(models.User).filter_by(email=get_setting(db, "aging_sender_email").strip().lower(), active=True).first()
    if emails and sender:
        queue_mail(db, sender, {"to": join_emails(emails), "cc": "", "subject": title,
                                "body": f"{title}.\n\nOpen HireModus > Tests > Needs grading to review the answers and recording."}, title)


def expire_if_due(db: Session, a: models.TestAssignment) -> bool:
    if a.status == "in_progress" and a.deadline and datetime.utcnow() >= a.deadline:
        finish(db, a, auto=True)
        a.events = list(a.events or []) + [{"t": datetime.utcnow().isoformat() + "Z", "type": "time_expired"}]
        return True
    return False
