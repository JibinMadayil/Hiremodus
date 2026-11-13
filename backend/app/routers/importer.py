"""Import the existing Excel candidate tracker (.xlsm / .xlsx).

Columns are matched by header text, so the sheet layout can drift a little. Each sheet maps to a
stage (and a department for the department sheets)."""
import os
import uuid
from datetime import datetime, date, timedelta

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..perms import require
from ..services import audit, clean_email, fmt_date, fmt_time, local_now
from ..aging import cfg as aging_cfg, initial_clock

router = APIRouter(prefix="/api/import", tags=["import"])

IMPORT_DIR = os.environ.get("HIREMODUS_IMPORT_DIR", "./imports")

# (test, field) in priority order; test is applied to the lowercased, trimmed header
HEADER_RULES = [
    (lambda h: h.startswith("sr") and "no" in h, "_skip"),
    (lambda h: "first name" in h, "first_name"),
    (lambda h: "last name" in h, "last_name"),
    (lambda h: "email" in h, "email"),
    (lambda h: h in ("resume", "resume link", "cv"), "resume_link"),
    (lambda h: "screening result" in h, "screening_result"),
    (lambda h: "screening comment" in h or "educational qualification" in h, "screening_comments"),
    (lambda h: "experienced in oracle" in h, "oracle_experience"),
    (lambda h: h.startswith("area fit"), "area_fit"),
    (lambda h: "ribbon" in h, "ribbon_rating"),
    (lambda h: h.startswith("interview link"), "ai_interview_link"),
    (lambda h: "interview id" in h and "1" in h, "_r1_entry"),
    (lambda h: "interview id" in h and "2" in h, "_r2_entry"),
    (lambda h: "preliminary interview" in h, "round1_info"),
    (lambda h: h.startswith("second round"), "round2_info"),
    (lambda h: "test score" in h, "test_score"),
    (lambda h: "interviewer comment" in h, "interviewer_comment"),
    (lambda h: h == "interviewer", "interviewer"),
    (lambda h: "practice" in h, "practice"),
    (lambda h: "final decision" in h, "final_decision"),
    (lambda h: "date added" in h, "date_added"),
    (lambda h: h == "location", "location"),
    (lambda h: h == "source", "source"),
    (lambda h: "phone" in h, "phone"),
    (lambda h: h == "position", "position"),
]

FIELD_LABELS = {
    "first_name": "First name", "last_name": "Last name", "email": "Email", "resume_link": "Resume",
    "location": "Location", "source": "Source", "screening_result": "Screening result",
    "screening_comments": "Screening comments", "oracle_experience": "Experienced in Oracle?",
    "area_fit": "Area fit", "ribbon_rating": "Ribbon rating", "ai_interview_link": "AI interview link",
    "round1_info": "Round 1 date/notes", "round2_info": "Round 2 date/notes", "test_score": "Test score",
    "interviewer": "Interviewer", "interviewer_comment": "Interviewer comment", "practice": "Practice",
    "final_decision": "Final decision", "date_added": "Date added", "phone": "Phone", "position": "Position",
    "_r1_entry": "Outlook invite ID, round 1", "_r2_entry": "Outlook invite ID, round 2",
    "_module": "Round 1 module", "_skip": "(skipped)",
}

# sheet name -> (stage name, department name)
SHEET_ROUTES = {
    "master": ("Screening", None),
    "no ai": ("AI Interview Pending", None),
    "ai sent": ("AI Interview Sent", None),
    "hired": ("Hired", None),
    "rejected": ("Rejected", None),
    "withdrawn": ("Withdrawn", None),
}


def map_header(h: str) -> str:
    key = " ".join(str(h or "").strip().lower().split())
    for test, field in HEADER_RULES:
        if test(key):
            return field
    return "custom:" + str(h).strip()


def find_header_row(ws) -> int | None:
    for i, r in enumerate(ws.iter_rows(min_row=1, max_row=8, values_only=True), 1):
        if any(isinstance(v, str) and "email" in v.lower() for v in r or []):
            return i
    return None


def sheet_columns(ws, hrow: int) -> list[tuple[int, str, str]]:
    header = next(ws.iter_rows(min_row=hrow, max_row=hrow, values_only=True))
    cols = []
    for idx, h in enumerate(header):
        if h is not None and str(h).strip():
            cols.append((idx, str(h).strip(), map_header(h)))
    # the round-1 module sits in the unlabelled column just after "Interview ID (Round 2)"
    last = max((i for i, _, f in cols), default=-1)
    if any(f == "_r2_entry" for _, _, f in cols):
        cols.append((last + 1, "(module column)", "_module"))
    return cols


def is_data_row(r: tuple, cols) -> bool:
    for idx, _, f in cols:
        if f in ("first_name", "last_name", "email") and idx < len(r) and r[idx] not in (None, ""):
            return True
    return False


def load(path: str):
    try:
        return openpyxl.load_workbook(path, data_only=True, read_only=False)
    except Exception:
        raise HTTPException(400, "Couldn't open that file. If it has a sensitivity label, save an unprotected copy first.")


def default_route(db: Session, sheet: str) -> dict:
    s = sheet.strip().lower()
    stages = {st.name.lower(): st for st in db.query(models.Stage)}
    depts = {d.name.lower(): d for d in db.query(models.Department)}
    if s in ("module selection", "modules"):
        return {"action": "modules"}
    if s in ("holidays", "holiday"):
        return {"action": "holidays"}
    if s in SHEET_ROUTES:
        st_name, _ = SHEET_ROUTES[s]
        st = stages.get(st_name.lower())
        return {"action": "candidates", "stage_id": st.id if st else None, "department_id": None}
    if s in depts:
        st = stages.get("department review")
        return {"action": "candidates", "stage_id": st.id if st else None, "department_id": depts[s].id}
    return {"action": "skip"}


@router.post("/preview")
async def preview(file: UploadFile = File(...), user=Depends(require("import.run")), db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".xlsx", ".xlsm"):
        raise HTTPException(400, "Upload an .xlsx or .xlsm file")
    os.makedirs(IMPORT_DIR, exist_ok=True)
    token = uuid.uuid4().hex
    path = os.path.join(IMPORT_DIR, token + ext)
    data = await file.read()
    if data[:4] != b"PK\x03\x04":
        raise HTTPException(400, "This workbook is encrypted (probably a Microsoft sensitivity label). "
                                 "Save a copy with the label set to General or Public and upload that.")
    with open(path, "wb") as fh:
        fh.write(data)
    wb = load(path)
    existing = {e for (e,) in db.query(func.lower(models.Candidate.email)).filter(models.Candidate.email != "")}
    sheets = []
    for ws in wb.worksheets:
        route = default_route(db, ws.title)
        info = {"sheet": ws.title, **route, "rows": 0, "columns": [], "sample": [], "already_in_app": 0}
        if route["action"] == "modules":
            info["rows"] = sum(1 for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0])
        elif route["action"] == "holidays":
            info["rows"] = sum(1 for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0])
        else:
            hrow = find_header_row(ws)
            if hrow:
                cols = sheet_columns(ws, hrow)
                info["columns"] = [{"header": h, "field": f, "label": FIELD_LABELS.get(f, f.replace("custom:", "Extra: "))}
                                   for _, h, f in cols]
                email_idx = next((i for i, _, f in cols if f == "email"), None)
                for r in ws.iter_rows(min_row=hrow + 1, values_only=True):
                    if not is_data_row(r, cols):
                        continue
                    info["rows"] += 1
                    if email_idx is not None and email_idx < len(r) and clean_email(str(r[email_idx] or "")) in existing:
                        info["already_in_app"] += 1
                    if len(info["sample"]) < 3:
                        info["sample"].append({h: _txt(r[i]) if i < len(r) else "" for i, h, _ in cols[:6]})
            elif route["action"] == "candidates":
                info["action"] = "skip"
        sheets.append(info)
    return {"token": token + ext, "file_name": file.filename, "sheets": sheets}


def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        if v.hour == 0 and v.minute == 0:
            return fmt_date(v)
        return f"{fmt_date(v)} {fmt_time(v)}"
    if isinstance(v, date):
        return fmt_date(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


class SheetChoice(BaseModel):
    sheet: str
    action: str  # candidates | modules | holidays | skip
    stage_id: int | None = None
    department_id: int | None = None


class CommitIn(BaseModel):
    token: str
    sheets: list[SheetChoice]
    skip_existing: bool = True
    replace_modules: bool = True
    create_interviews: bool = True


@router.post("/commit")
def commit(body: CommitIn, user=Depends(require("import.run")), db: Session = Depends(get_db)):
    path = os.path.join(IMPORT_DIR, os.path.basename(body.token))
    if not os.path.exists(path):
        raise HTTPException(400, "The upload expired. Please upload the file again.")
    wb = load(path)
    summary = {"candidates": 0, "skipped_existing": 0, "interviews": 0, "modules": 0, "holidays": 0, "sheets": []}

    # modules first, so the AMS module column can link to them
    for choice in body.sheets:
        if choice.action == "modules" and choice.sheet in wb.sheetnames:
            summary["modules"] += import_modules(db, wb[choice.sheet], body.replace_modules)
        if choice.action == "holidays" and choice.sheet in wb.sheetnames:
            summary["holidays"] += import_holidays(db, wb[choice.sheet])
    db.flush()
    modules = list(db.query(models.Module).filter(models.Module.active))
    aging_conf = aging_cfg(db)
    now_local = local_now()
    templates = list(db.query(models.InterviewTemplate))

    seen = set()
    if body.skip_existing:
        seen = {(e, s) for e, s in db.query(func.lower(models.Candidate.email), models.Candidate.stage_id)
                .filter(models.Candidate.email != "")}

    for choice in body.sheets:
        if choice.action != "candidates" or choice.sheet not in wb.sheetnames:
            continue
        ws = wb[choice.sheet]
        hrow = find_header_row(ws)
        if not hrow:
            continue
        cols = sheet_columns(ws, hrow)
        added = skipped = 0
        for r in ws.iter_rows(min_row=hrow + 1, values_only=True):
            if not is_data_row(r, cols):
                continue
            c = models.Candidate(stage_id=choice.stage_id, department_id=choice.department_id, custom={})
            extra = {}
            r1 = r2 = None
            r1_entry = r2_entry = ""
            sheet_dates = []
            for idx, header, field in cols:
                v = r[idx] if idx < len(r) else None
                if v is None or (isinstance(v, str) and not v.strip()):
                    continue
                if field == "_skip":
                    continue
                if field == "_r1_entry":
                    r1_entry = str(v).strip()
                elif field == "_r2_entry":
                    r2_entry = str(v).strip()
                elif field == "_module":
                    m = match_module(modules, str(v))
                    if m:
                        c.module_id = m.id
                    else:
                        extra["Round 1 module"] = _txt(v)
                elif field == "date_added":
                    c.date_added = v.date() if isinstance(v, datetime) else None
                    if isinstance(v, datetime):
                        sheet_dates.append(v)
                    if c.date_added is None:
                        extra["Date added"] = _txt(v)
                elif field in ("round1_info", "round2_info"):
                    setattr(c, field, _txt(v))
                    if isinstance(v, datetime):
                        sheet_dates.append(v)
                    if isinstance(v, datetime) and (v.hour or v.minute):
                        if field == "round1_info":
                            r1 = v
                        else:
                            r2 = v
                elif field.startswith("custom:"):
                    extra[header] = _txt(v)
                else:
                    val = _txt(v)
                    if field == "email":
                        val = clean_email(val)
                    setattr(c, field, val[:2000])
            c.first_name = (c.first_name or "").strip()
            c.last_name = (c.last_name or "").strip()
            c.custom = extra
            key = ((c.email or "").lower(), choice.stage_id)
            if body.skip_existing and c.email and key in seen:
                skipped += 1
                continue
            seen.add(key)
            initial_clock(c, sheet_dates, aging_conf, now_local)
            db.add(c)
            db.flush()
            added += 1
            if body.create_interviews and choice.department_id:
                for rnd, when, entry in ((1, r1, r1_entry), (2, r2, r2_entry)):
                    if when:
                        tpl = next((t for t in templates if t.department_id == choice.department_id
                                    and t.round_number == rnd), None)
                        dur = tpl.duration_min if tpl else (30 if rnd == 1 else 60)
                        db.add(models.Interview(
                            candidate_id=c.id, template_id=tpl.id if tpl else None, round_number=rnd,
                            title=f"{tpl.round_label if tpl else f'Round {rnd}'} - {c.first_name} {c.last_name} (imported)",
                            start=when, end=when + timedelta(minutes=dur), location=tpl.location if tpl else "",
                            required=c.email, status="scheduled", outlook_entry_id=entry, organizer_id=user.id))
                        summary["interviews"] += 1
        summary["candidates"] += added
        summary["skipped_existing"] += skipped
        summary["sheets"].append({"sheet": choice.sheet, "added": added, "skipped": skipped})

    audit(db, user, "excel_import",
          f"{summary['candidates']} candidates, {summary['interviews']} interviews, {summary['modules']} modules")
    db.commit()
    try:
        os.remove(path)
    except OSError:
        pass
    return summary


def match_module(modules: list[models.Module], text: str) -> models.Module | None:
    t = text.strip().lower()
    if not t:
        return None
    for m in modules:
        if m.name.strip().lower() == t:
            return m
    hits = [m for m in modules if t in m.name.lower()]
    return hits[0] if len(hits) == 1 else None


def import_modules(db: Session, ws, replace: bool) -> int:
    names = []
    n = 0
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not r[0] or not str(r[0]).strip():
            continue
        name = str(r[0]).strip()
        names.append(name.lower())
        m = db.query(models.Module).filter(func.lower(models.Module.name) == name.lower()).first()
        if not m:
            m = models.Module(name=name)
            db.add(m)
        m.web_link = str(r[1]).strip() if len(r) > 1 and r[1] else ""
        m.training_link = str(r[2]).strip() if len(r) > 2 and r[2] else ""
        m.active = True
        n += 1
    if replace and names:
        for m in db.query(models.Module):
            if m.name.lower() not in names:
                in_use = db.query(models.Candidate).filter_by(module_id=m.id).count()
                if in_use:
                    m.active = False
                else:
                    db.delete(m)
    return n


def import_holidays(db: Session, ws) -> int:
    n = 0
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not r[0]:
            continue
        v = r[0]
        d = v.date() if isinstance(v, datetime) else v if isinstance(v, date) else None
        if not d:
            continue
        if not db.query(models.Holiday).filter_by(day=d).first():
            db.add(models.Holiday(day=d, name=str(r[1]).strip() if len(r) > 1 and r[1] else ""))
            n += 1
    return n
