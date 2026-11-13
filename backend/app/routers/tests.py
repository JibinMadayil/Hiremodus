import os
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..security import hash_password, random_password, random_code, make_token, decode_token, current_user
from ..perms import require, require_any, has, dept_scope, limit_full
from ..services import audit, queue_mail, candidate_context, render, get_setting
from ..testsvc import create_assignment, test_ctx, expire_if_due, grade_auto
from ..util import row, rows, get_or_404, apply
from .candidates import check_visible

router = APIRouter(prefix="/api", tags=["tests"])


def test_out(t: models.Test, with_answers=True) -> dict:
    d = row(t)
    d["questions"] = [row(q) if with_answers else dict(row(q), correct_index=None) for q in t.questions]
    d["total_points"] = sum(q.points or 0 for q in t.questions)
    if t.pool_choice or t.pool_written:
        ch = sorted((q.points or 0 for q in t.questions if q.kind in ("mcq", "multi")), reverse=True)
        wr = sorted((q.points or 0 for q in t.questions if q.kind not in ("mcq", "multi")), reverse=True)
        d["pool_note"] = f"Each candidate gets {t.pool_choice or len(ch)} of {len(ch)} choice and {t.pool_written or len(wr)} of {len(wr)} written questions"
    return d


def test_in_scope(user, t: models.Test) -> bool:
    scope = dept_scope(user)
    return scope is None or bool(set(t.department_ids or []) & set(scope))


def scoped_test(db, user, tid) -> models.Test:
    t = get_or_404(db, models.Test, tid, "Test")
    if not test_in_scope(user, t):
        raise HTTPException(403, "This test belongs to another department")
    return t


@router.get("/tests")
def list_tests(user=Depends(require("tests.papers")), db: Session = Depends(get_db)):
    return [test_out(t) for t in db.query(models.Test).order_by(models.Test.name) if test_in_scope(user, t)]


@router.get("/tests/{tid}")
def get_test(tid: int, user=Depends(require("tests.papers")), db: Session = Depends(get_db)):
    return test_out(scoped_test(db, user, tid))


class QIn(BaseModel):
    id: int | None = None
    kind: str = "mcq"
    prompt: str
    options: list[str] = []
    correct_index: int | None = None
    correct_indices: list[int] = []
    points: float = 1
    section: str = ""
    image: str = ""
    option_images: list[str] = []


class TestIn(BaseModel):
    name: str
    department_id: int | None = None
    department_ids: list[int] = []
    duration_min: int = 30
    instructions: str = ""
    allow_file_upload: bool = False
    shuffle_questions: bool = False
    shuffle_options: bool = False
    pool_choice: int | None = None
    pool_written: int | None = None
    code_valid_minutes: int = 30
    record_camera: bool = True
    record_audio: bool = True
    record_screen: bool = True
    active: bool = True
    questions: list[QIn] = []


def save_test(db, t: models.Test, body: TestIn, user=None):
    if not body.department_ids and body.department_id:
        body.department_ids = [body.department_id]
    body.department_ids = sorted(set(body.department_ids))
    if not body.department_ids:
        raise HTTPException(400, "Pick the department(s) this test is for")
    if user is not None:
        scope = dept_scope(user)
        if scope is not None and not set(body.department_ids) <= set(scope):
            raise HTTPException(403, "You can only save tests for your own departments")
    body.department_id = body.department_ids[0]
    data = body.model_dump(exclude={"questions"})
    apply(t, data)
    existing = {q.id: q for q in t.questions}
    keep = []
    for i, qi in enumerate(body.questions):
        if qi.kind not in ("mcq", "multi", "short", "long", "file"):
            raise HTTPException(400, f"Unknown question type {qi.kind}")
        if qi.kind == "file" and not body.allow_file_upload:
            raise HTTPException(400, "Turn on file upload for this test before adding a file question")
        if not qi.prompt.strip():
            raise HTTPException(400, f"Question {i + 1} has no text")
        if qi.kind in ("mcq", "multi"):
            if len([o for o in qi.options if o.strip()]) != len(qi.options):
                raise HTTPException(400, f"Question {i + 1} has an empty option. Remove it or fill it in.")
            if len(qi.options) < 2:
                raise HTTPException(400, f"Question {i + 1} needs at least two options")
        if qi.kind == "mcq" and (qi.correct_index is None or not (0 <= qi.correct_index < len(qi.options))):
            raise HTTPException(400, f"Question {i + 1} needs a correct answer")
        if qi.kind == "multi":
            qi.correct_indices = sorted({x for x in qi.correct_indices if 0 <= x < len(qi.options)})
            if len(qi.correct_indices) < 1:
                raise HTTPException(400, f"Question {i + 1} needs at least one correct answer ticked")
        q = existing.get(qi.id) if qi.id else None
        if q is None:
            q = models.Question()
        choice = qi.kind in ("mcq", "multi")
        q.kind, q.prompt, q.options, q.points, q.sort = qi.kind, qi.prompt, qi.options if choice else [], qi.points, i
        q.correct_index = qi.correct_index if qi.kind == "mcq" else None
        q.correct_indices = qi.correct_indices if qi.kind == "multi" else []
        q.section = qi.section.strip()[:100]
        q.image = qi.image if qi.image.startswith("/api/test-images/") else ""
        imgs = [x if x.startswith("/api/test-images/") else "" for x in (qi.option_images or [])]
        q.option_images = (imgs + [""] * len(q.options))[:len(q.options)] if choice else []
        keep.append(q)
    t.questions = keep
    n_choice = sum(1 for q in keep if q.kind in ("mcq", "multi"))
    n_written = len(keep) - n_choice
    for field, n, label in (("pool_choice", n_choice, "multiple choice"), ("pool_written", n_written, "written")):
        v = getattr(t, field)
        if v is not None and (v < 1 or v > n):
            raise HTTPException(400, f"The {label} pool can draw between 1 and {n} questions (leave empty to use all)")


@router.post("/tests")
def create_test(body: TestIn, user=Depends(require("tests.papers")), db: Session = Depends(get_db)):
    t = models.Test(name=body.name)
    save_test(db, t, body, user)
    db.add(t)
    db.commit()
    return test_out(t)


@router.put("/tests/{tid}")
def update_test(tid: int, body: TestIn, user=Depends(require("tests.papers")), db: Session = Depends(get_db)):
    t = scoped_test(db, user, tid)
    started = db.query(models.TestAssignment).filter(models.TestAssignment.test_id == tid,
                                                     models.TestAssignment.status == "in_progress").count()
    if started:
        raise HTTPException(400, "A candidate is taking this test right now. Try again after they submit.")
    save_test(db, t, body, user)
    db.commit()
    return test_out(t)


@router.delete("/tests/{tid}")
def delete_test(tid: int, user=Depends(require("tests.papers")), db: Session = Depends(get_db)):
    t = scoped_test(db, user, tid)
    if db.query(models.TestAssignment).filter_by(test_id=tid).count():
        t.active = False  # keep history of results
    else:
        db.delete(t)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- Excel test papers

@router.get("/test-paper/template.xlsx")
def paper_template(user=Depends(require("tests.papers"))):
    from fastapi.responses import Response
    from ..testpaper import build_template
    return Response(build_template(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="HireModus test paper template.xlsx"'})


@router.post("/test-paper/preview")
async def paper_preview(file: UploadFile = File(...), user=Depends(require("tests.papers")), db: Session = Depends(get_db)):
    from ..testpaper import read_paper
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Upload the filled-in template as an .xlsx file")
    data = await file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(400, "The file is over 25 MB. Make the pictures smaller and try again.")
    depts = {d.name.lower(): d.id for d in db.query(models.Department)}
    out = read_paper(data, save_image_bytes, depts)
    scope = dept_scope(user)
    if scope is not None:
        bad = [d for d in out["details"].get("department_ids", []) if d not in scope]
        if bad:
            names = ", ".join(db.get(models.Department, d).name for d in bad)
            out["errors"].insert(0, f"Test details: you don't work in {names}, so you can't create a test for it.")
    return out


class PaperCommit(BaseModel):
    mode: str  # new | add | replace
    test_id: int | None = None
    details: dict = {}
    questions: list[QIn]


@router.post("/test-paper/commit")
def paper_commit(body: PaperCommit, user=Depends(require("tests.papers")), db: Session = Depends(get_db)):
    if not body.questions:
        raise HTTPException(400, "There are no questions to save")
    new_qs = [QIn(**{**q.model_dump(), "id": None}) for q in body.questions]
    if body.mode == "new":
        d = body.details or {}
        if not str(d.get("name") or "").strip():
            raise HTTPException(400, "Give the test a name")
        t = models.Test(name=str(d["name"]).strip())
        tin = TestIn(name=t.name, department_ids=d.get("department_ids") or [], duration_min=int(d.get("duration_min") or 30),
                     instructions=d.get("instructions") or "", shuffle_questions=bool(d.get("shuffle_questions")),
                     shuffle_options=bool(d.get("shuffle_options")), pool_choice=d.get("pool_choice"),
                     pool_written=d.get("pool_written"), allow_file_upload=any(q.kind == "file" for q in new_qs),
                     questions=new_qs)
        save_test(db, t, tin, user)
        db.add(t)
        action = "created from upload"
    elif body.mode in ("add", "replace"):
        if not body.test_id:
            raise HTTPException(400, "Pick the test to update")
        t = scoped_test(db, user, body.test_id)
        if db.query(models.TestAssignment).filter_by(test_id=t.id, status="in_progress").count():
            raise HTTPException(400, "A candidate is taking this test right now. Try again after they submit.")
        current = test_out(t)
        keep = [QIn(**{k: q.get(k) if q.get(k) is not None else QIn.model_fields[k].default for k in QIn.model_fields})
                for q in current["questions"]] if body.mode == "add" else []
        fields = {k: current.get(k) for k in TestIn.model_fields if k != "questions" and current.get(k) is not None}
        fields["allow_file_upload"] = bool(fields.get("allow_file_upload")) or any(q.kind == "file" for q in new_qs)
        if body.mode == "replace":
            fields["pool_choice"] = fields["pool_written"] = None
        save_test(db, t, TestIn(**fields, questions=keep + new_qs), user)
        action = "questions added from upload" if body.mode == "add" else "questions replaced from upload"
    else:
        raise HTTPException(400, "Unknown mode")
    db.flush()
    audit(db, user, f"Test {t.name}: {action}", f"{len(new_qs)} question(s)")
    db.commit()
    return test_out(t)


# ---------------------------------------------------------------- assignments

class AssignIn(BaseModel):
    test_id: int
    send_email: bool = True


@router.post("/candidates/{cid}/assign-test")
def assign_test(cid: int, body: AssignIn, user=Depends(require("tests.assign")), db: Session = Depends(get_db)):
    c = check_visible(db, user, cid)
    test = scoped_test(db, user, body.test_id)
    a, pw = create_assignment(db, c, test)
    audit(db, user, "test_assigned", f"{test.name} (login {a.username})", c.id)
    if body.send_email:
        send_login_email(db, user, c, a, pw, test)
    db.commit()
    return {"assignment": row(a, {"password_hash", "code_hash"}), "password": pw}


def send_login_email(db, user, c, a, pw, test):
    if not c.email:
        raise HTTPException(400, "This candidate has no email address")
    tpl = db.query(models.EmailTemplate).filter_by(key="test_access").first()
    ctx = candidate_context(db, c, user)
    ctx.update(test_ctx(db, a, pw, test))
    subject = render(tpl.subject if tpl else "Your assessment login - {{company}}", ctx)
    body = render(tpl.body if tpl else "Good Day {{first_name}},\n\n{{test_block}}\n\nThank you", ctx)
    queue_mail(db, user, {"to": c.email, "cc": "", "subject": subject, "body": body},
               f"Test login: {c.first_name} {c.last_name}", c.id)


def assignment_for_staff(db, user, aid) -> tuple[models.TestAssignment, models.Candidate]:
    a = get_or_404(db, models.TestAssignment, aid, "Test assignment")
    c = check_visible(db, user, a.candidate_id)
    return a, c


@router.get("/assignments")
def list_assignments(status: str = "", user=Depends(require_any("tests.results", "tests.papers", "tests.start_code")), db: Session = Depends(get_db)):
    q = (db.query(models.TestAssignment, models.Candidate, models.Test)
         .join(models.Candidate, models.Candidate.id == models.TestAssignment.candidate_id)
         .join(models.Test, models.Test.id == models.TestAssignment.test_id))
    if status:
        q = q.filter(models.TestAssignment.status.in_(status.split(",")))
    q = limit_full(q, db, user)
    out = []
    changed = False
    for a, c, t in q.order_by(models.TestAssignment.created_at.desc()).limit(500):
        changed |= expire_if_due(db, a)
        d = row(a, {"password_hash", "code_hash"})
        d.update(candidate_name=f"{c.first_name} {c.last_name}".strip(), test_name=t.name,
                 code_active=bool(a.code_hash and a.code_expires and a.code_expires > datetime.utcnow()))
        out.append(d)
    if changed:
        db.commit()
    return out


@router.post("/assignments/{aid}/start-code")
def start_code(aid: int, user=Depends(require("tests.start_code")), db: Session = Depends(get_db)):
    a, c = assignment_for_staff(db, user, aid)
    expire_if_due(db, a)
    if a.status not in ("assigned", "in_progress"):
        raise HTTPException(400, f"This test is already {a.status}")
    test = db.get(models.Test, a.test_id)
    code = random_code(6)
    a.code_hash = hash_password(code)
    a.code_expires = datetime.utcnow() + timedelta(minutes=test.code_valid_minutes or 30)
    a.code_issued_by = user.id
    audit(db, user, "start_code_issued", f"{test.name}, valid {test.code_valid_minutes} min", c.id)
    db.commit()
    return {"code": code, "expires": a.code_expires.isoformat() + "Z", "valid_minutes": test.code_valid_minutes}


@router.post("/assignments/{aid}/reset-password")
def reset_password(aid: int, send_email: bool = True, user=Depends(require("tests.assign")), db: Session = Depends(get_db)):
    a, c = assignment_for_staff(db, user, aid)
    if a.status in ("submitted", "graded"):
        raise HTTPException(400, "This test is already submitted")
    pw = random_password()
    a.password_hash = hash_password(pw)
    if a.status == "revoked":
        a.status = "assigned"
    test = db.get(models.Test, a.test_id)
    if send_email:
        send_login_email(db, user, c, a, pw, test)
    audit(db, user, "test_password_reset", test.name, c.id)
    db.commit()
    return {"username": a.username, "password": pw}


@router.post("/assignments/{aid}/revoke")
def revoke(aid: int, user=Depends(require("tests.assign")), db: Session = Depends(get_db)):
    a, c = assignment_for_staff(db, user, aid)
    if a.status in ("submitted", "graded"):
        raise HTTPException(400, "This test is already submitted")
    a.status = "revoked"
    a.code_hash = None
    audit(db, user, "test_revoked", "", c.id)
    db.commit()
    return {"ok": True}


@router.post("/assignments/{aid}/force-submit")
def force_submit(aid: int, user=Depends(require("tests.start_code")), db: Session = Depends(get_db)):
    from ..testsvc import finish
    a, c = assignment_for_staff(db, user, aid)
    if a.status != "in_progress":
        raise HTTPException(400, "Only a test in progress can be submitted")
    finish(db, a)
    a.events = list(a.events or []) + [{"t": datetime.utcnow().isoformat() + "Z", "type": "submitted_by_staff", "by": user.name}]
    audit(db, user, "test_force_submitted", "", c.id)
    db.commit()
    return {"ok": True}


@router.get("/assignments/{aid}")
def get_assignment(aid: int, user=Depends(require_any("tests.results", "tests.papers")), db: Session = Depends(get_db)):
    a, c = assignment_for_staff(db, user, aid)
    if expire_if_due(db, a):
        db.commit()
    test = db.get(models.Test, a.test_id)
    answers = {x.question_id: x for x in db.query(models.Answer).filter_by(assignment_id=a.id)}
    qs = []
    drawn = set(a.question_order or [q.id for q in test.questions])
    for q in test.questions:
        if q.id not in drawn:
            continue
        ans = answers.get(q.id)
        qs.append({"question": row(q), "answer": row(ans) if ans else None})
    d = row(a, {"password_hash", "code_hash"})
    recs = []
    for r in db.query(models.Recording).filter_by(assignment_id=a.id).order_by(models.Recording.started_at):
        recs.append({
            "id": r.id, "kind": r.kind, "mime": r.mime, "bytes": r.bytes, "deleted": r.deleted,
            "started_at": r.started_at.isoformat() + "Z", "last_chunk_at": (r.last_chunk_at.isoformat() + "Z") if r.last_chunk_at else None,
            "delete_at": r.delete_at.isoformat() + "Z",
            "url": None if r.deleted or not r.bytes else f"/api/recordings/{r.id}/file?t={make_token(str(r.id), 'rec', 4)}",
        })
    snaps = []
    for sn in db.query(models.Snapshot).filter_by(assignment_id=a.id).order_by(models.Snapshot.at):
        snaps.append({"id": sn.id, "kind": sn.kind, "detail": sn.detail, "at": sn.at.isoformat() + "Z", "deleted": sn.deleted,
                      "url": None if sn.deleted else f"/api/snapshots/{sn.id}/file?t={make_token('s' + str(sn.id), 'rec', 4)}"})
    d["snapshots"] = snaps
    papers = has(user, "tests.papers")
    if not papers:
        qs = []
    if not has(user, "tests.results") and not papers:
        recs = []
    d["can_see_papers"] = papers
    d.update(candidate_name=f"{c.first_name} {c.last_name}".strip(), candidate_id=c.id,
             test={"id": test.id, "name": test.name, "duration_min": test.duration_min}, items=qs, recordings=recs,
             code_active=bool(a.code_hash and a.code_expires and a.code_expires > datetime.utcnow()))
    return d


class GradeItem(BaseModel):
    question_id: int
    score: float | None = None
    comment: str = ""


class GradeIn(BaseModel):
    items: list[GradeItem]
    reviewer_notes: str = ""
    final: bool = False


@router.put("/assignments/{aid}/grade")
def grade(aid: int, body: GradeIn, user=Depends(require("tests.papers")), db: Session = Depends(get_db)):
    a, c = assignment_for_staff(db, user, aid)
    if a.status not in ("submitted", "graded"):
        raise HTTPException(400, "The candidate hasn't submitted yet")
    test = db.get(models.Test, a.test_id)
    qmap = {q.id: q for q in test.questions}
    answers = {x.question_id: x for x in db.query(models.Answer).filter_by(assignment_id=a.id)}
    for it in body.items:
        q = qmap.get(it.question_id)
        if not q or q.kind in ("mcq", "multi"):
            continue
        if it.score is not None and not (0 <= it.score <= (q.points or 0)):
            raise HTTPException(400, f"Score must be between 0 and {q.points}")
        ans = answers.get(q.id)
        if ans is None:
            ans = models.Answer(assignment_id=a.id, question_id=q.id, value="")
            db.add(ans)
            answers[q.id] = ans
        ans.score, ans.comment = it.score, it.comment
    db.flush()
    grade_auto(db, a)
    manual = sum((answers[q.id].score or 0) for q in test.questions if q.kind not in ("mcq", "multi") and q.id in answers)
    a.manual_score = manual
    a.reviewer_notes = body.reviewer_notes
    if body.final:
        a.status = "graded"
    audit(db, user, "test_graded" if body.final else "test_grading_saved",
          f"{(a.auto_score or 0) + manual:g} / {a.total_points:g}", c.id)
    db.commit()
    return {"ok": True}


@router.get("/assignments/{aid}/file/{answer_id}")
def download(aid: int, answer_id: int, user=Depends(require("tests.papers")), db: Session = Depends(get_db)):
    a, c = assignment_for_staff(db, user, aid)
    ans = get_or_404(db, models.Answer, answer_id, "Answer")
    if ans.assignment_id != a.id or not ans.file_path or not os.path.exists(ans.file_path):
        raise HTTPException(404, "File not found")
    return FileResponse(ans.file_path, filename=ans.file_name or "upload")


@router.get("/snapshots/{sid}/file")
def snapshot_file(sid: int, t: str, db: Session = Depends(get_db)):
    data = decode_token(t)
    if data.get("scope") != "rec" or data.get("sub") != "s" + str(sid):
        raise HTTPException(403, "Link expired. Reopen the results page.")
    sn = db.get(models.Snapshot, sid)
    if not sn or sn.deleted or not sn.path or not os.path.exists(sn.path):
        raise HTTPException(404, "This picture has been deleted")
    return FileResponse(sn.path, media_type="image/jpeg")


@router.get("/recordings/{rid}/file")
def recording_file(rid: int, t: str, db: Session = Depends(get_db)):
    """Video elements can't send an auth header, so playback links carry a short-lived signed token instead."""
    data = decode_token(t)
    if data.get("scope") != "rec" or data.get("sub") != str(rid):
        raise HTTPException(403, "Link expired. Reopen the results page.")
    r = db.get(models.Recording, rid)
    if not r or r.deleted or not r.path or not os.path.exists(r.path):
        raise HTTPException(404, "This recording has been deleted")
    return FileResponse(r.path, media_type=(r.mime or "video/webm").split(";")[0])


# ---------------------------------------------------------------- pictures in questions

IMG_DIR = os.path.join(os.environ.get("HIREMODUS_UPLOAD_DIR", "./uploads"), "test-images")
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def save_image_bytes(data: bytes, ext: str) -> str:
    import uuid
    ext = ext.lower() if ext.lower() in IMG_EXT else ".png"
    os.makedirs(IMG_DIR, exist_ok=True)
    name = uuid.uuid4().hex + ext
    with open(os.path.join(IMG_DIR, name), "wb") as fh:
        fh.write(data)
    return f"/api/test-images/{name}"


@router.post("/test-images")
async def upload_test_image(file: UploadFile = File(...), user=Depends(require("tests.papers"))):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in IMG_EXT:
        raise HTTPException(400, "Use a PNG, JPG, GIF or WebP picture")
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Pictures must be under 5 MB")
    return {"url": save_image_bytes(data, ext)}


@router.get("/test-images/{name}")
def get_test_image(name: str):
    # random file names; candidates load these during the test without a staff login
    if not re.fullmatch(r"[0-9a-f]{32}\.[a-z]{3,4}", name):
        raise HTTPException(404, "Not found")
    path = os.path.join(IMG_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})
