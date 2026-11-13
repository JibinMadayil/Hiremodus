import os
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..security import hash_password, current_user
from ..perms import require, dept_scope, PERMISSIONS, user_perms, limit_full
from ..services import audit
from ..services import all_settings, set_setting, get_setting, PLACEHOLDER_HELP, local_now, split_emails, join_emails, DEFAULT_SETTINGS
from ..util import row, rows, get_or_404, apply
from .auth import user_out

router = APIRouter(prefix="/api", tags=["admin"])

SIMPLE = {
    "departments": (models.Department, models.Department.sort),
    "stages": (models.Stage, models.Stage.sort),
    "email-templates": (models.EmailTemplate, models.EmailTemplate.name),
    "interview-templates": (models.InterviewTemplate, models.InterviewTemplate.name),
    "modules": (models.Module, models.Module.name),
    "holidays": (models.Holiday, models.Holiday.day),
    "custom-fields": (models.CustomField, models.CustomField.sort),
}
EMAIL_FIELDS = {"cc_emails", "cc", "required_emails", "optional_emails", "flex_emails", "flex_preferred_emails"}


@router.get("/meta")
def meta(user=Depends(current_user), db: Session = Depends(get_db)):
    s = all_settings(db)
    return {
        "me": user_out(user),
        "stages": rows(db.query(models.Stage).order_by(models.Stage.sort)),
        "departments": rows(db.query(models.Department).order_by(models.Department.sort)),
        "modules": rows(db.query(models.Module).order_by(models.Module.name)),
        "email_templates": [dict(id=t.id, key=t.key, name=t.name, show_as_action=t.show_as_action,
                                 department_ids=t.department_ids or [], active=t.active,
                                 moves_to_stage_id=t.moves_to_stage_id)
                            for t in db.query(models.EmailTemplate).order_by(models.EmailTemplate.name)],
        "interview_templates": [dict(id=t.id, name=t.name, department_id=t.department_id, round_number=t.round_number,
                                     round_label=t.round_label, duration_min=t.duration_min, active=t.active,
                                     requires_module=t.requires_module, reuse_previous_module=t.reuse_previous_module,
                                     includes_test=t.includes_test, test_id=t.test_id, ask_extra_cc=t.ask_extra_cc,
                                     search_offset_days=t.search_offset_days)
                                for t in db.query(models.InterviewTemplate).order_by(models.InterviewTemplate.sort, models.InterviewTemplate.name)],
        "tests": [dict(id=t.id, name=t.name, department_id=t.department_id, department_ids=t.department_ids or [], active=t.active, duration_min=t.duration_min)
                  for t in db.query(models.Test).order_by(models.Test.name)],
        "users": [dict(id=u.id, name=u.name, email=u.email) for u in db.query(models.User).filter(models.User.active)],
        "settings": {k: s.get(k, "") for k in ("company_name", "portal_base_url", "simulate_outlook", "ai_link_prefix",
                                                "brand_name", "brand_tagline", "brand_color", "brand_navy", "brand_logo",
                                                "aging_enabled", "aging_alert_days", "aging_reject_days", "aging_auto_reject",
                                                "feedback_enabled", "retention_enabled", "retention_months", "replies_enabled",
                                                "ms_graph_enabled")},
        "placeholders": PLACEHOLDER_HELP,
        "roles": rows(db.query(models.Role).order_by(models.Role.builtin.desc(), models.Role.name)),
        "permissions": PERMISSIONS,
        "custom_fields": rows(db.query(models.CustomField).filter(models.CustomField.active).order_by(models.CustomField.sort)),
    }


def dept_filter(db, user, department_id: int | None):
    """The department picked on the dashboard, checked against what this person may see."""
    if not department_id:
        return None
    scope = dept_scope(user)
    if scope is not None and department_id not in scope:
        raise HTTPException(403, "You don't work in that department")
    return department_id


@router.get("/dashboard")
def dashboard(mine: bool = True, department_id: int | None = None, user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    dep = dept_filter(db, user, department_id)
    cand_dep = (lambda q: q.filter(models.Candidate.department_id == dep)) if dep else (lambda q: q)
    q = cand_dep(db.query(models.Candidate.stage_id, func.count()).group_by(models.Candidate.stage_id))
    if mine:
        q = limit_full(q, db, user)
    by_stage = {sid: n for sid, n in q.all()}
    q2 = db.query(models.Candidate.department_id, func.count()).group_by(models.Candidate.department_id)
    by_dept = {did: n for did, n in q2.all()}
    now = local_now()
    upcoming = limit_full(cand_dep(db.query(models.Interview, models.Candidate)
                          .join(models.Candidate, models.Candidate.id == models.Interview.candidate_id)
                          .filter(models.Interview.start >= now.replace(hour=0, minute=0), models.Interview.status != "cancelled",
                                  models.Interview.start <= now + timedelta(days=7))), db, user).order_by(models.Interview.start).limit(25).all()
    failed = db.query(models.OutboxJob).filter(models.OutboxJob.status == "failed", models.OutboxJob.owner_id == user.id).count()
    queued = db.query(models.OutboxJob).filter(models.OutboxJob.status.in_(["queued", "claimed"]),
                                               models.OutboxJob.owner_id == user.id, models.OutboxJob.kind != "free_busy").count()
    ta = lambda st: limit_full(cand_dep(db.query(models.TestAssignment).join(models.Candidate, models.Candidate.id == models.TestAssignment.candidate_id)
                               .filter(models.TestAssignment.status == st)), db, user).count()
    to_grade, live = ta("submitted"), ta("in_progress")
    scope = dept_scope(user)
    transfers = []
    tq = db.query(models.Transfer, models.Candidate).join(models.Candidate, models.Candidate.id == models.Transfer.candidate_id).filter(models.Transfer.status == "pending")
    names = {d.id: d.name for d in db.query(models.Department)}
    for t, c in tq.order_by(models.Transfer.requested_at):
        if (scope is None or t.to_department_id in scope) and (not dep or t.to_department_id == dep):
            transfers.append({"id": t.id, "candidate_id": c.id, "candidate_name": f"{c.first_name} {c.last_name}".strip(),
                              "from": names.get(t.from_department_id, ""), "to": names.get(t.to_department_id, ""),
                              "note": t.note, "requested_at": t.requested_at.isoformat() + "Z"})
    # replies this person hasn't opened, newest first
    rq = limit_full(cand_dep(db.query(models.CandidateEmail, models.Candidate)
                             .join(models.Candidate, models.Candidate.id == models.CandidateEmail.candidate_id)), db, user)
    replies = []
    for e, c in rq.order_by(models.CandidateEmail.received_at.desc()).limit(500):
        if user.id in (e.read_by or []):
            continue
        replies.append({"id": e.id, "candidate_id": c.id, "candidate_name": f"{c.first_name} {c.last_name}".strip(),
                        "department_id": c.department_id, "subject": e.subject, "preview": e.preview,
                        "received_at": e.received_at.isoformat() + "Z"})
    return {
        "department_id": dep,
        "by_stage": by_stage, "by_department": by_dept,
        "upcoming": [dict(row(i), candidate_name=f"{c.first_name} {c.last_name}".strip()) for i, c in upcoming],
        "outbox_failed": failed, "outbox_waiting": queued, "tests_to_grade": to_grade, "tests_live": live,
        "transfers": transfers, "unread_replies": len(replies), "replies": replies[:15],
    }


# ---------------------------------------------------------------- settings

@router.get("/settings")
def get_settings(user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    return all_settings(db)


@router.put("/settings")
def put_settings(body: dict, user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    for k, v in body.items():
        if k in DEFAULT_SETTINGS and not k.startswith("ms_"):  # Microsoft 365 settings have their own page
            if k in ("global_cc", "it_emails", "it_cc", "aging_recipients", "notify_test_submitted_emails", "notify_auto_rejected_emails"):
                v = join_emails(str(v))
            if k == "aging_sender_email":
                v = str(v).strip().lower()
            if k in ("retention_months", "retention_warn_days", "replies_lookback_days"):
                try:
                    v = str(max(1, min(120 if k == "retention_months" else 90, int(float(v)))))
                except (TypeError, ValueError):
                    raise HTTPException(400, "Use a whole number")
            if k == "recording_quality" and v not in ("low", "standard", "high"):
                raise HTTPException(400, "Recording quality must be low, standard or high")
            if k in ("detect_looking_away_seconds", "detect_no_face_seconds"):
                try:
                    v = str(max(2, min(60, int(float(v)))))
                except (TypeError, ValueError):
                    raise HTTPException(400, "Detection times must be a number of seconds")
            set_setting(db, k, str(v))
    db.commit()
    return all_settings(db)


# ---------------------------------------------------------------- generic lists

def model_for(kind: str):
    if kind not in SIMPLE:
        raise HTTPException(404, "Unknown list")
    return SIMPLE[kind]


@router.get("/admin/{kind}")
def list_kind(kind: str, user=Depends(current_user), db: Session = Depends(get_db)):
    model, order = model_for(kind)
    return rows(db.query(model).order_by(order))


def clean(body: dict) -> dict:
    body = dict(body)
    body.pop("id", None)
    for k in EMAIL_FIELDS:
        if k in body and isinstance(body[k], str):
            body[k] = join_emails(body[k])
    return body


@router.post("/admin/{kind}")
def create_kind(kind: str, body: dict, user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    model, _ = model_for(kind)
    obj = model()
    apply(obj, clean(body))
    if kind == "email-templates" and not obj.key:
        obj.key = f"custom_{int(datetime.utcnow().timestamp())}"
    if kind == "custom-fields":
        if not (obj.label or "").strip():
            raise HTTPException(400, "Give the field a label")
        base = re.sub(r"[^a-z0-9]+", "_", obj.label.lower()).strip("_")[:40] or "field"
        key, n = base, 1
        while db.query(models.CustomField).filter_by(key=key).first():
            n += 1
            key = f"{base}_{n}"
        obj.key = key
    db.add(obj)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(400, f"Could not save: {str(e.__cause__ or e)[:200]}")
    return row(obj)


@router.put("/admin/{kind}/{oid}")
def update_kind(kind: str, oid: int, body: dict, user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    model, _ = model_for(kind)
    obj = get_or_404(db, model, oid)
    data = clean(body)
    if kind in ("email-templates", "custom-fields"):
        data.pop("key", None)  # keys are referenced by the app and by stored values
    apply(obj, data)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(400, f"Could not save: {str(e.__cause__ or e)[:200]}")
    return row(obj)


BUILTIN_TEMPLATES = {"rejection", "withdrawal", "reschedule", "test_access", "ai_invite", "aging_alert"}


@router.delete("/admin/{kind}/{oid}")
def delete_kind(kind: str, oid: int, user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    model, _ = model_for(kind)
    obj = get_or_404(db, model, oid)
    if kind == "email-templates" and obj.key in BUILTIN_TEMPLATES:
        raise HTTPException(400, "This template is used by the app. Edit it or turn it off instead.")
    if kind == "stages" and db.query(models.Candidate).filter_by(stage_id=oid).count():
        raise HTTPException(400, "Candidates are still in this stage. Move them first or turn the stage off.")
    if kind == "departments" and db.query(models.Candidate).filter_by(department_id=oid).count():
        raise HTTPException(400, "Candidates still belong to this department. Turn it off instead.")
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.post("/admin/{kind}/reorder")
def reorder(kind: str, ids: list[int], user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    model, _ = model_for(kind)
    for i, oid in enumerate(ids):
        obj = db.get(model, oid)
        if obj is not None and hasattr(obj, "sort"):
            obj.sort = i
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- users

def role_names(roles) -> str:
    return ", ".join(sorted(r.name for r in roles)) or "no role"


@router.get("/users")
def list_users(user=Depends(require("users.manage")), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.query(models.User).order_by(models.User.name)]


def load_roles(db, ids) -> list:
    roles = db.query(models.Role).filter(models.Role.id.in_(ids or [])).all()
    if not roles:
        raise HTTPException(400, "Pick at least one role")
    return roles


@router.post("/users")
def create_user(body: dict, user=Depends(require("users.manage")), db: Session = Depends(get_db)):
    email = (body.get("email") or "").strip().lower()
    if not email or not body.get("name"):
        raise HTTPException(400, "Name and email are required")
    if db.query(models.User).filter_by(email=email).first():
        raise HTTPException(400, "A user with that email already exists")
    pw = body.get("password") or ""
    if len(pw) < 8:
        raise HTTPException(400, "Temporary password must be at least 8 characters")
    roles = load_roles(db, body.get("role_ids"))
    u = models.User(name=body["name"].strip(), email=email, role=roles[0].key, password_hash=hash_password(pw),
                    must_change_password=True)
    u.roles = roles
    u.departments = db.query(models.Department).filter(models.Department.id.in_(body.get("department_ids") or [])).all()
    db.add(u)
    audit(db, user, "user_created", f"{u.name} <{u.email}> as {role_names(roles)}")
    db.commit()
    return user_out(u)


@router.put("/users/{uid}")
def update_user(uid: int, body: dict, user=Depends(require("users.manage")), db: Session = Depends(get_db)):
    u = get_or_404(db, models.User, uid, "User")
    if "name" in body and body["name"].strip() and body["name"].strip() != u.name:
        audit(db, user, "user_renamed", f"{u.name} → {body['name'].strip()}")
        u.name = body["name"].strip()
    if "role_ids" in body:
        new = load_roles(db, body["role_ids"])
        if u.id == user.id and not any("users.manage" in (r.permissions or []) for r in new):
            raise HTTPException(400, "You can't remove your own permission to manage users")
        before, after = role_names(u.roles), role_names(new)
        if before != after:
            u.roles = new
            u.role = new[0].key
            audit(db, user, "user_roles_changed", f"{u.name}: {before} → {after}")
    if "active" in body and bool(body["active"]) != u.active:
        if u.id == user.id and not body["active"]:
            raise HTTPException(400, "You can't disable your own account")
        u.active = bool(body["active"])
        audit(db, user, "user_enabled" if u.active else "user_disabled", u.name)
    if "department_ids" in body:
        new = db.query(models.Department).filter(models.Department.id.in_(body["department_ids"] or [])).all()
        if sorted(d.id for d in new) != sorted(d.id for d in u.departments):
            audit(db, user, "user_departments_changed", f"{u.name}: {', '.join(d.name for d in u.departments) or 'none'} → {', '.join(d.name for d in new) or 'none'}")
            u.departments = new
    if body.get("password"):
        if len(body["password"]) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        u.password_hash = hash_password(body["password"])
        u.must_change_password = True
        audit(db, user, "user_password_reset", u.name)
    db.commit()
    return user_out(u)


# ---------------------------------------------------------------- roles

@router.get("/roles")
def list_roles(user=Depends(current_user), db: Session = Depends(get_db)):
    counts = dict(db.query(models.user_roles.c.role_id, func.count()).group_by(models.user_roles.c.role_id).all())
    return [dict(row(r), users=counts.get(r.id, 0)) for r in db.query(models.Role).order_by(models.Role.builtin.desc(), models.Role.name)]


def clean_perms(perms) -> list[str]:
    return [p for p in (perms or []) if p in PERMISSIONS]


@router.post("/roles")
def create_role(body: dict, user=Depends(require("users.manage")), db: Session = Depends(get_db)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Give the role a name")
    if db.query(models.Role).filter(func.lower(models.Role.name) == name.lower()).first():
        raise HTTPException(400, "A role with that name exists")
    r = models.Role(name=name, key=f"custom_{int(datetime.utcnow().timestamp())}", permissions=clean_perms(body.get("permissions")),
                    department_scoped=bool(body.get("department_scoped")), description=body.get("description", ""))
    db.add(r)
    audit(db, user, "role_created", f"{name}: {', '.join(r.permissions) or 'no permissions'}")
    db.commit()
    return row(r)


@router.put("/roles/{rid}")
def update_role(rid: int, body: dict, user=Depends(require("users.manage")), db: Session = Depends(get_db)):
    r = get_or_404(db, models.Role, rid, "Role")
    perms = clean_perms(body.get("permissions", r.permissions))
    if r in user.roles and "users.manage" not in perms and not any("users.manage" in (x.permissions or []) for x in user.roles if x.id != r.id):
        raise HTTPException(400, "That would remove your own permission to manage users")
    changes = []
    if set(perms) != set(r.permissions or []):
        added, removed = sorted(set(perms) - set(r.permissions or [])), sorted(set(r.permissions or []) - set(perms))
        changes.append(("added " + ", ".join(added) if added else "") + ("; " if added and removed else "") + ("removed " + ", ".join(removed) if removed else ""))
        r.permissions = perms
    if "department_scoped" in body and bool(body["department_scoped"]) != r.department_scoped:
        r.department_scoped = bool(body["department_scoped"])
        changes.append("department limit " + ("on" if r.department_scoped else "off"))
    if body.get("name") and body["name"].strip() != r.name:
        changes.append(f"renamed from {r.name}")
        r.name = body["name"].strip()
    if "description" in body:
        r.description = body["description"]
    if changes:
        audit(db, user, "role_changed", f"{r.name}: {'; '.join(changes)}")
    db.commit()
    return row(r)


@router.delete("/roles/{rid}")
def delete_role(rid: int, user=Depends(require("users.manage")), db: Session = Depends(get_db)):
    r = get_or_404(db, models.Role, rid, "Role")
    if r.builtin:
        raise HTTPException(400, "Admin and Recruiter can't be deleted. Edit their permissions instead.")
    if db.query(models.user_roles).filter(models.user_roles.c.role_id == rid).count():
        raise HTTPException(400, "Users still have this role. Change their roles first.")
    audit(db, user, "role_deleted", r.name)
    db.delete(r)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- audit log

@router.get("/audit")
def audit_log(q: str = "", action: str = "", limit: int = 500, user=Depends(require("audit.view")), db: Session = Depends(get_db)):
    query = db.query(models.AuditLog)
    if action:
        query = query.filter(models.AuditLog.action.in_(action.split(",")))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter((models.AuditLog.detail.ilike(like)) | (models.AuditLog.user_name.ilike(like)) | (models.AuditLog.action.ilike(like)))
    names = {c.id: f"{c.first_name} {c.last_name}".strip() for c in db.query(models.Candidate.id, models.Candidate.first_name, models.Candidate.last_name)}
    out = []
    for a in query.order_by(models.AuditLog.at.desc()).limit(min(limit, 2000)):
        d = row(a)
        d["candidate_name"] = names.get(a.candidate_id, "") if a.candidate_id else ""
        out.append(d)
    return out


# ---------------------------------------------------------------- aging + notifications

@router.get("/aging")
def aging_overview(department_id: int | None = None, user=Depends(require("candidates.view")), db: Session = Depends(get_db)):
    from ..aging import kpis
    return kpis(db, user, dept_filter(db, user, department_id))


@router.post("/aging/run")
def aging_run_now(user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    from ..aging import run
    audit(db, user, "aging_run_manual", "")
    db.commit()
    return run(db, force=True)


def visible_notifications(db, user):
    mine = user_perms(user)
    q = db.query(models.Notification).order_by(models.Notification.at.desc()).limit(100)
    return [n for n in q if (n.user_id == user.id) or (n.user_id is None and n.permission in mine)]


@router.get("/notifications")
def notifications(user=Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for n in visible_notifications(db, user):
        d = row(n, {"read_by"})
        d["read"] = user.id in (n.read_by or [])
        out.append(d)
    return {"items": out, "unread": sum(1 for x in out if not x["read"])}


@router.post("/notifications/read-all")
def notifications_read(user=Depends(current_user), db: Session = Depends(get_db)):
    for n in visible_notifications(db, user):
        if user.id not in (n.read_by or []):
            n.read_by = list(n.read_by or []) + [user.id]
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- personal preferences (saved views, dashboard tiles)

@router.get("/me/prefs")
def get_prefs(user=Depends(current_user)):
    return user.prefs or {}


@router.put("/me/prefs")
def put_prefs(body: dict, user=Depends(current_user), db: Session = Depends(get_db)):
    prefs = dict(user.prefs or {})
    for k in ("candidate_views", "candidate_columns", "dashboard_tiles", "candidate_layout"):
        if k in body:
            prefs[k] = body[k]
    user.prefs = prefs
    db.commit()
    return prefs


# ---------------------------------------------------------------- branding

BRAND_DIR = os.path.join(os.environ.get("HIREMODUS_UPLOAD_DIR", "./uploads"), "branding")


@router.post("/branding/logo")
async def upload_logo(file: UploadFile = File(...), user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
        raise HTTPException(400, "Use a PNG, JPG, SVG or WebP image")
    data = await file.read(3 * 1024 * 1024 + 1)
    if len(data) > 3 * 1024 * 1024:
        raise HTTPException(400, "Logo must be under 3 MB")
    os.makedirs(BRAND_DIR, exist_ok=True)
    for old in os.listdir(BRAND_DIR):
        os.remove(os.path.join(BRAND_DIR, old))
    with open(os.path.join(BRAND_DIR, "logo" + ext), "wb") as fh:
        fh.write(data)
    set_setting(db, "brand_logo", f"/api/branding/logo?v={int(datetime.utcnow().timestamp())}")
    audit(db, user, "branding_logo_changed", file.filename or "")
    db.commit()
    return {"brand_logo": get_setting(db, "brand_logo")}


@router.delete("/branding/logo")
def remove_logo(user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    if os.path.isdir(BRAND_DIR):
        for old in os.listdir(BRAND_DIR):
            os.remove(os.path.join(BRAND_DIR, old))
    set_setting(db, "brand_logo", "")
    db.commit()
    return {"ok": True}


@router.get("/branding/logo")
def get_logo():
    if os.path.isdir(BRAND_DIR):
        for f in os.listdir(BRAND_DIR):
            return FileResponse(os.path.join(BRAND_DIR, f))
    raise HTTPException(404, "No logo uploaded")


@router.get("/branding")
def branding(db: Session = Depends(get_db)):
    """Public: the login page and candidate portal use this before anyone signs in."""
    return {k: get_setting(db, k) for k in ("brand_name", "brand_tagline", "brand_color", "brand_navy", "brand_logo", "company_name")}


# ---------------------------------------------------------------- clearing out old candidate data

@router.get("/retention")
def retention_overview(user=Depends(require("users.manage")), db: Session = Depends(get_db)):
    from .. import retention
    stages = {s.id: s.name for s in db.query(models.Stage)}
    names = {d.id: d.name for d in db.query(models.Department)}
    up = [{"id": c.id, "name": f"{c.first_name} {c.last_name}".strip(), "stage": stages.get(c.stage_id, ""),
           "department": names.get(c.department_id, ""), "since": c.stage_changed_at.isoformat() + "Z" if c.stage_changed_at else None,
           "clears_on": due.date().isoformat(), "warned": bool(c.retention_warned_at)}
          for c, due in retention.upcoming(db, within_days=60)]
    kept = [{"id": c.id, "name": f"{c.first_name} {c.last_name}".strip(), "stage": stages.get(c.stage_id, "")}
            for c in db.query(models.Candidate).filter(models.Candidate.retention_keep.is_(True)).order_by(models.Candidate.last_name)]
    return {"enabled": retention.enabled(db), "months": retention.months(db), "warn_days": retention.warn_days(db),
            "cleared_total": db.query(models.Candidate).filter(models.Candidate.anonymized_at.isnot(None)).count(),
            "upcoming": up, "kept": kept}


class KeepIn(BaseModel):
    keep: bool


@router.put("/candidates/{cid}/retention-keep")
def retention_keep(cid: int, body: KeepIn, user=Depends(require("users.manage")), db: Session = Depends(get_db)):
    c = db.get(models.Candidate, cid)
    if not c:
        raise HTTPException(404, "Candidate not found")
    if c.anonymized_at:
        raise HTTPException(400, "This candidate's details were already removed")
    c.retention_keep = body.keep
    if not body.keep:
        c.retention_warned_at = None  # a fresh warning goes out before anything is removed
    audit(db, user, "retention_keep_on" if body.keep else "retention_keep_off", "", candidate_id=c.id)
    db.commit()
    return {"keep": c.retention_keep}
