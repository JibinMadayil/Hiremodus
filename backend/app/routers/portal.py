"""Candidate test portal. A candidate token can only reach these endpoints."""
import os
import random
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..security import verify_password, make_token, candidate_session, decode_token, bearer
from ..services import audit
from ..testsvc import expire_if_due, finish

router = APIRouter(prefix="/api/portal", tags=["portal"])

UPLOAD_DIR = os.environ.get("HIREMODUS_UPLOAD_DIR", "./uploads")
MAX_UPLOAD = 20 * 1024 * 1024
ALLOWED_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".sql", ".png", ".jpg", ".jpeg", ".zip", ".rtf"}
MAX_LOGIN_FAILS = 8
MAX_CODE_FAILS = 5


def now():
    return datetime.utcnow()


def log_event(a: models.TestAssignment, kind: str, detail: str = ""):
    ev = list(a.events or [])
    if len(ev) < 2000:
        ev.append({"t": now().isoformat() + "Z", "type": kind, "detail": detail[:300]})
    a.events = ev


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    a = db.query(models.TestAssignment).filter_by(username=body.username.strip().lower()).first()
    generic = HTTPException(401, "Username or password is incorrect")
    if not a:
        raise generic
    if a.locked_until and a.locked_until > now():
        raise HTTPException(429, "Too many attempts. Please ask your interviewer for help.")
    if not verify_password(body.password.strip(), a.password_hash):
        a.login_failures = (a.login_failures or 0) + 1
        if a.login_failures >= MAX_LOGIN_FAILS:
            a.locked_until = now() + timedelta(minutes=15)
            a.login_failures = 0
        db.commit()
        raise generic
    a.login_failures = 0
    expire_if_due(db, a)
    if a.status == "revoked":
        raise HTTPException(403, "This test login is no longer active.")
    if a.status in ("submitted", "graded"):
        db.commit()
        raise HTTPException(403, "You have already submitted this test. Thank you.")
    log_event(a, "signed_in")
    db.commit()
    return {"token": make_token(str(a.id), "cand-login", 12), **state(db, a)}


def state(db: Session, a: models.TestAssignment) -> dict:
    test = db.get(models.Test, a.test_id)
    c = db.get(models.Candidate, a.candidate_id)
    return {
        "status": a.status,
        "first_name": c.first_name if c else "",
        "test_name": test.name,
        "duration_min": test.duration_min,
        "instructions": test.instructions,
        "question_count": len(test.questions),
        "allow_file_upload": test.allow_file_upload,
        "record": recording_flags(test),
        "integrity": integrity_settings(db),
    }


def integrity_settings(db: Session) -> dict:
    from ..services import get_setting
    g = lambda k: get_setting(db, k)
    return {"quality": g("recording_quality") or "high", "detect": g("detect_enabled") == "true",
            "phone": g("detect_phone") == "true", "warn": g("detect_warn_candidate") == "true",
            "away_s": int(g("detect_looking_away_seconds") or 5), "noface_s": int(g("detect_no_face_seconds") or 5)}


def recording_flags(test: models.Test) -> dict:
    return {"camera": bool(test.record_camera), "audio": bool(test.record_camera and test.record_audio),
            "screen": bool(test.record_screen)}


@router.get("/state")
def get_state(sess=Depends(candidate_session), db: Session = Depends(get_db)):
    a, _ = sess
    if expire_if_due(db, a):
        db.commit()
    return state(db, a)


class UnlockIn(BaseModel):
    code: str


@router.post("/unlock")
def unlock(body: UnlockIn, sess=Depends(candidate_session), db: Session = Depends(get_db)):
    a, _ = sess
    expire_if_due(db, a)
    if a.status not in ("assigned", "in_progress"):
        db.commit()
        raise HTTPException(403, "This test is closed.")
    code = "".join(ch for ch in body.code if ch.isdigit())
    if not a.code_hash or not a.code_expires or a.code_expires < now():
        raise HTTPException(400, "There is no active start code. Ask your interviewer for a new one.")
    if not verify_password(code, a.code_hash):
        a.code_failures = (a.code_failures or 0) + 1
        log_event(a, "wrong_code")
        if a.code_failures >= MAX_CODE_FAILS:
            a.code_hash = None
            a.code_failures = 0
            db.commit()
            raise HTTPException(400, "Too many wrong codes. Ask your interviewer for a new code.")
        db.commit()
        raise HTTPException(400, "That code is not correct.")
    test = db.get(models.Test, a.test_id)
    a.code_hash = None  # one-time
    a.code_failures = 0
    a.session_id = secrets.token_hex(16)
    first_start = a.status == "assigned"
    if first_start:
        a.status = "in_progress"
        a.started_at = now()
        a.deadline = a.started_at + timedelta(minutes=test.duration_min)
        choice = [q for q in test.questions if q.kind in ("mcq", "multi")]
        written = [q for q in test.questions if q.kind not in ("mcq", "multi")]
        if test.pool_choice and test.pool_choice < len(choice):
            keep = {q.id for q in random.sample(choice, test.pool_choice)}
            choice = [q for q in choice if q.id in keep]
        if test.pool_written and test.pool_written < len(written):
            keep = {q.id for q in random.sample(written, test.pool_written)}
            written = [q for q in written if q.id in keep]
        picked = {q.id for q in choice + written}
        ids = [q.id for q in test.questions if q.id in picked]
        if test.shuffle_questions:
            random.shuffle(ids)
        a.question_order = ids
        orders = {}
        if test.shuffle_options:
            for q in choice:
                perm = list(range(len(q.options or [])))
                random.shuffle(perm)
                orders[str(q.id)] = perm
        a.option_orders = orders
        log_event(a, "started")
    else:
        log_event(a, "resumed", "Test reopened with a new start code; the timer kept running")
    c = db.get(models.Candidate, a.candidate_id)
    audit(db, None, "test_started" if first_start else "test_resumed", test.name, c.id if c else None)
    db.commit()
    token = make_token(str(a.id), "cand-test", (test.duration_min / 60) + 1, {"sid": a.session_id})
    return {"token": token}


def test_session(sess=Depends(candidate_session), creds=Depends(bearer), db: Session = Depends(get_db)):
    a, scope = sess
    if scope != "cand-test":
        raise HTTPException(403, "Enter the start code first")
    sid = decode_token(creds.credentials).get("sid")
    if sid != a.session_id:
        raise HTTPException(409, "This test was opened on another device. Ask your interviewer for help.")
    if expire_if_due(db, a):
        db.commit()
    if a.status != "in_progress":
        raise HTTPException(410, "This test has been submitted.")
    return a


@router.get("/test")
def get_test(a=Depends(test_session), db: Session = Depends(get_db)):
    test = db.get(models.Test, a.test_id)
    qmap = {q.id: q for q in test.questions}
    order = assigned_ids(a, test)
    answers = {x.question_id: x for x in db.query(models.Answer).filter_by(assignment_id=a.id)}
    qs = []
    for i, qid in enumerate(order):
        q = qmap[qid]
        ans = answers.get(qid)
        perm = shown_order(a, q)
        value = ans.value if ans else ""
        if q.kind in ("mcq", "multi") and value:
            value = ",".join(str(perm.index(int(x))) for x in value.split(",") if x.isdigit() and int(x) in perm)
        oimgs = (q.option_images or []) + [""] * len(q.options or [])
        qs.append({
            "id": q.id, "number": i + 1, "kind": q.kind, "prompt": q.prompt, "options": [q.options[k] for k in perm] if q.options else [],
            "section": q.section or "", "image": q.image or "", "option_images": [oimgs[k] for k in perm] if q.options else [],
            "points": q.points, "value": value, "file_name": ans.file_name if ans else "",
        })
    remaining = max(0, int((a.deadline - now()).total_seconds()))
    return {"test_name": test.name, "instructions": test.instructions, "remaining_seconds": remaining,
            "questions": qs, "allow_file_upload": test.allow_file_upload, "record": recording_flags(test),
            "integrity": integrity_settings(db)}


def assigned_ids(a: models.TestAssignment, test: models.Test) -> list[int]:
    ids = {q.id for q in test.questions}
    if a.question_order:
        return [i for i in a.question_order if i in ids]
    return [q.id for q in test.questions]


def shown_order(a: models.TestAssignment, q: models.Question) -> list[int]:
    perm = (a.option_orders or {}).get(str(q.id))
    n = len(q.options or [])
    return perm if perm and len(perm) == n else list(range(n))


class AnswerIn(BaseModel):
    value: str


def get_question(db, a, qid) -> models.Question:
    q = db.get(models.Question, qid)
    if not q or q.test_id != a.test_id:
        raise HTTPException(404, "Question not found")
    return q


def get_answer(db, a, qid) -> models.Answer:
    ans = db.query(models.Answer).filter_by(assignment_id=a.id, question_id=qid).first()
    if not ans:
        ans = models.Answer(assignment_id=a.id, question_id=qid, value="")
        db.add(ans)
    return ans


@router.put("/answers/{qid}")
def save_answer(qid: int, body: AnswerIn, a=Depends(test_session), db: Session = Depends(get_db)):
    q = get_question(db, a, qid)
    if q.kind == "file":
        raise HTTPException(400, "Upload a file for this question")
    if q.id not in assigned_ids(a, db.get(models.Test, a.test_id)):
        raise HTTPException(404, "Question not found")
    v = body.value[:20000]
    if q.kind == "mcq" and v != "" and not (v.isdigit() and int(v) < len(q.options or [])):
        raise HTTPException(400, "Invalid choice")
    if q.kind == "multi" and v != "":
        parts = v.split(",")
        if not all(x.isdigit() and int(x) < len(q.options or []) for x in parts):
            raise HTTPException(400, "Invalid choice")
        v = ",".join(sorted(set(parts), key=int))
    if q.kind in ("mcq", "multi") and v != "":
        perm = shown_order(a, q)  # candidate saw shuffled options; store the original positions
        v = ",".join(str(x) for x in sorted(perm[int(x)] for x in v.split(",")))
    get_answer(db, a, qid).value = v
    db.commit()
    return {"ok": True}


@router.post("/answers/{qid}/file")
async def upload(qid: int, file: UploadFile = File(...), a=Depends(test_session), db: Session = Depends(get_db)):
    q = get_question(db, a, qid)
    test = db.get(models.Test, a.test_id)
    if q.kind != "file" or not test.allow_file_upload:
        raise HTTPException(400, "This question doesn't take a file")
    name = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"File type {ext or '(none)'} isn't allowed")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, "File is larger than 20 MB")
    folder = os.path.join(UPLOAD_DIR, str(a.id))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{qid}-{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as fh:
        fh.write(data)
    ans = get_answer(db, a, qid)
    if ans.file_path and os.path.exists(ans.file_path):
        os.remove(ans.file_path)
    ans.file_path, ans.file_name, ans.value = path, name, name
    log_event(a, "file_uploaded", name)
    db.commit()
    return {"file_name": name}


class EventIn(BaseModel):
    type: str
    detail: str = ""


ALLOWED_EVENTS = {"phone_detected", "no_face", "multiple_faces", "looking_away", "second_screen", "detection_unavailable",
                  "unsupported_browser", "camera_stopped", "screen_stopped", "recording_resumed", "recording_error", "fullscreen_exit", "fullscreen_enter", "tab_hidden", "window_blur", "copy_blocked",
                  "paste_blocked", "cut_blocked", "context_menu_blocked", "shortcut_blocked", "print_blocked",
                  "devtools_key", "page_reload"}


@router.post("/events")
def event(body: EventIn, sess=Depends(candidate_session), db: Session = Depends(get_db)):
    a, scope = sess
    if body.type not in ALLOWED_EVENTS:
        raise HTTPException(400, "Unknown event")
    if a.status == "in_progress":
        log_event(a, body.type, body.detail)
        db.commit()
    return {"ok": True}


@router.post("/submit")
def submit(a=Depends(test_session), db: Session = Depends(get_db)):
    finish(db, a)
    log_event(a, "submitted")
    c = db.get(models.Candidate, a.candidate_id)
    audit(db, None, "test_submitted", "", c.id if c else None)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- recording

MAX_CHUNK = 25 * 1024 * 1024


def rec_session(sess=Depends(candidate_session), creds=Depends(bearer), db: Session = Depends(get_db)):
    """Like test_session, but lets the last few seconds of video arrive just after the test is submitted."""
    a, scope = sess
    if scope != "cand-test" or decode_token(creds.credentials).get("sid") != a.session_id:
        raise HTTPException(403, "Not allowed")
    if a.status == "in_progress":
        return a
    if a.status in ("submitted", "graded") and a.submitted_at and now() - a.submitted_at < timedelta(minutes=3):
        return a
    raise HTTPException(410, "This test has been submitted.")


class RecStart(BaseModel):
    kind: str
    mime: str = "video/webm"


@router.post("/recording/start")
def recording_start(body: RecStart, a=Depends(rec_session), db: Session = Depends(get_db)):
    from ..recsvc import next_local_midnight_utc, recording_path
    test = db.get(models.Test, a.test_id)
    flags = recording_flags(test)
    if body.kind not in ("camera", "screen") or not flags[body.kind]:
        raise HTTPException(400, "This test doesn't record that")
    r = models.Recording(assignment_id=a.id, kind=body.kind, mime=body.mime[:100] or "video/webm",
                         started_at=now(), delete_at=next_local_midnight_utc())
    db.add(r)
    db.flush()
    r.path = recording_path(a.id, r.id, body.kind)
    open(r.path, "wb").close()
    db.commit()
    return {"id": r.id}


@router.post("/recording/{rid}/chunk")
async def recording_chunk(rid: int, seq: int, request: Request, a=Depends(rec_session), db: Session = Depends(get_db)):
    r = db.get(models.Recording, rid)
    if not r or r.assignment_id != a.id or r.deleted or not r.path:
        raise HTTPException(404, "Recording not found")
    if seq < r.chunks:
        return {"ok": True, "duplicate": True}
    if seq > r.chunks:
        raise HTTPException(409, f"Expected chunk {r.chunks}")
    data = await request.body()
    if len(data) > MAX_CHUNK:
        raise HTTPException(413, "Chunk too large")
    with open(r.path, "ab") as fh:
        fh.write(data)
    r.chunks += 1
    r.bytes += len(data)
    r.last_chunk_at = now()
    db.commit()
    return {"ok": True}



SNAP_KINDS = {"phone_detected", "no_face", "multiple_faces", "looking_away"}


@router.post("/snapshot")
async def snapshot(kind: str, request: Request, detail: str = "", a=Depends(rec_session), db: Session = Depends(get_db)):
    """Webcam still taken at the moment a check flagged something, kept until midnight like the recordings."""
    from ..recsvc import next_local_midnight_utc, REC_DIR
    if kind not in SNAP_KINDS:
        raise HTTPException(400, "Unknown kind")
    if db.query(models.Snapshot).filter_by(assignment_id=a.id).count() >= 300:
        return {"ok": True, "skipped": True}
    data = await request.body()
    if not data or len(data) > 2 * 1024 * 1024:
        raise HTTPException(400, "Bad image")
    folder = os.path.join(REC_DIR, str(a.id))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"snap-{uuid.uuid4().hex}.jpg")
    with open(path, "wb") as fh:
        fh.write(data)
    db.add(models.Snapshot(assignment_id=a.id, kind=kind, detail=detail[:300], path=path, delete_at=next_local_midnight_utc()))
    db.commit()
    return {"ok": True}
