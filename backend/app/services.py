"""Shared helpers: settings, email lists, template rendering, the outbox queue."""
import os
import re
import random
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from . import models

TZ = ZoneInfo(os.environ.get("HIREMODUS_TZ", "America/Toronto"))

DEFAULT_SETTINGS = {
    "company_name": "Novamodus Solutions Inc.",
    "global_cc": "",
    "it_emails": "",
    "it_cc": "",
    "instance_credentials_link": "",
    "portal_base_url": "http://localhost:8000/portal",
    "ai_link_prefix": "https://app.ribbon.ai/",
    "ai_interview_link": "",
    "simulate_outlook": "false",
    "duplicate_check": "true",
    # aging rules
    "aging_enabled": "true",
    "aging_alert_days": "30",
    "aging_reject_days": "45",
    "aging_auto_reject": "true",
    "aging_recipients": "areddy@novamodus.com",
    "aging_sender_email": "areddy@novamodus.com",
    "aging_run_time": "08:00",
    "aging_cc_department": "true",
    "aging_cc_last_contact": "true",
    "aging_reset_on_stage_change": "false",
    "aging_import_grace_days": "7",
    "aging_alert_mode": "daily",
    "aging_last_run": "",
    # test integrity
    "recording_quality": "high",
    "detect_enabled": "true",
    "detect_phone": "true",
    "detect_looking_away_seconds": "5",
    "detect_no_face_seconds": "5",
    "detect_warn_candidate": "true",
    # branding
    "brand_name": "HireModus",
    "brand_tagline": "BY NOVAMODUS",
    "brand_color": "#E5484D",
    "brand_navy": "#1B2A4A",
    "brand_logo": "",
    # notification rules
    "notify_test_submitted_inapp": "true",
    "notify_test_submitted_emails": "",
    "notify_auto_rejected_emails": "",
    "notify_new_duplicate_inapp": "true",
    # candidate replies
    "replies_enabled": "true",
    "replies_lookback_days": "30",
    # clearing out old candidate data
    "retention_enabled": "false",
    "retention_months": "12",
    "retention_warn_days": "14",
    # interview feedback
    "feedback_enabled": "true",
    # Microsoft 365 (Entra ID sign-in and Graph); edited only on the Microsoft 365 settings page
    "ms_tenant_id": "",
    "ms_client_id": "",
    "ms_public_url": "",
    "ms_signin_enabled": "false",
    "ms_password_signin": "everyone",  # everyone | admins (only used when Microsoft sign-in is on)
    "ms_graph_enabled": "false",
    "ms_default_transport": "connector",  # connector | graph
}

SECRET_SETTINGS = {"ms_client_secret"}  # never sent to the browser


def local_now() -> datetime:
    """Wall-clock time in the office time zone, as a naive datetime (all interview times are stored this way)."""
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


# ---------------------------------------------------------------- settings

def get_setting(db: Session, key: str) -> str:
    row = db.get(models.Setting, key)
    if row is None:
        return DEFAULT_SETTINGS.get(key, "")
    return row.value


def all_settings(db: Session) -> dict:
    out = dict(DEFAULT_SETTINGS)
    for row in db.query(models.Setting).all():
        if row.key not in SECRET_SETTINGS:
            out[row.key] = row.value
    return out


def set_setting(db: Session, key: str, value: str):
    row = db.get(models.Setting, key)
    if row is None:
        db.add(models.Setting(key=key, value=value))
        db.flush()
    else:
        row.value = value


def simulate(db: Session) -> bool:
    return get_setting(db, "simulate_outlook").lower() == "true"


# ---------------------------------------------------------------- email lists

_EMAIL_CHARS = re.compile(r"[^A-Za-z0-9._%+\-@]")


def clean_email(raw: str) -> str:
    """Drop invisible characters pasted from resumes/PDFs that make Outlook reject an address."""
    return _EMAIL_CHARS.sub("", raw or "").strip().lower()


def split_emails(text: str | None) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[;,\s]+", text)
    out, seen = [], set()
    for p in parts:
        e = clean_email(p)
        if e and "@" in e and e not in seen:
            seen.add(e)
            out.append(e)
    return out


def join_emails(*lists) -> str:
    seen, out = set(), []
    for lst in lists:
        if isinstance(lst, str):
            lst = split_emails(lst)
        for e in lst or []:
            e = clean_email(e)
            if e and e not in seen:
                seen.add(e)
                out.append(e)
    return "; ".join(out)


def minus(emails: list[str], remove: list[str]) -> list[str]:
    r = {clean_email(x) for x in remove}
    return [e for e in emails if clean_email(e) not in r]


# ---------------------------------------------------------------- templates

PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

PLACEHOLDER_HELP = {
    "first_name": "Candidate first name",
    "last_name": "Candidate last name",
    "full_name": "Candidate full name",
    "email": "Candidate email",
    "company": "Company name from Settings",
    "department": "Candidate's department",
    "position": "Position applied for",
    "resume_link": "Resume link",
    "resume_line": "'Resume: <link>' line, or nothing if no resume",
    "ai_interview_link": "AI interview link from Settings",
    "interview_date": "e.g. Monday, November 16, 2026",
    "interview_time": "e.g. 10:30 AM",
    "interview_end_time": "e.g. 11:00 AM",
    "location": "Interview location",
    "round": "Interview round label",
    "module": "Selected training module",
    "module_web_link": "Module's Oracle documentation link",
    "module_training_link": "Module's training portal link",
    "instance_link": "Oracle instance credentials link from Settings",
    "sender_name": "Name of the person sending",
    "due_date": "Today + the template's due days",
    "test_block": "Test login details (only when the interview includes a test)",
    "test_name": "Test name",
    "test_username": "Candidate's test username",
    "test_password": "Candidate's test password",
    "test_portal_url": "Test portal address",
}


def fmt_date(d: datetime | date | None) -> str:
    if not d:
        return ""
    return f"{d:%A, %B} {d.day}, {d:%Y}"


def fmt_time(d: datetime | None) -> str:
    if not d:
        return ""
    return d.strftime("%I:%M %p").lstrip("0")


def candidate_context(db: Session, c: models.Candidate, sender: models.User | None = None) -> dict:
    dept = db.get(models.Department, c.department_id) if c.department_id else None
    mod = db.get(models.Module, c.module_id) if c.module_id else None
    ctx = {
        "first_name": c.first_name,
        "last_name": c.last_name,
        "full_name": f"{c.first_name} {c.last_name}".strip(),
        "email": c.email,
        "company": get_setting(db, "company_name"),
        "department": dept.name if dept else "",
        "position": c.position,
        "resume_link": c.resume_link,
        "resume_line": f"Resume: {c.resume_link}" if c.resume_link else "",
        "ai_interview_link": get_setting(db, "ai_interview_link"),
        "instance_link": get_setting(db, "instance_credentials_link"),
        "sender_name": sender.name if sender else get_setting(db, "company_name"),
        "module": mod.name if mod else "",
        "module_web_link": mod.web_link if mod else "",
        "module_training_link": mod.training_link if mod else "",
        "test_block": "",
    }
    return ctx


def render(text: str, ctx: dict) -> str:
    out = PLACEHOLDER.sub(lambda m: str(ctx.get(m.group(1), "")), text or "")
    # collapse blank lines left behind by empty placeholders (e.g. no resume)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip("\n")


def build_template_email(db: Session, tpl: models.EmailTemplate, c: models.Candidate, sender: models.User,
                         extra_ctx: dict | None = None) -> dict:
    ctx = candidate_context(db, c, sender)
    if tpl.due_days:
        ctx["due_date"] = fmt_date(local_now() + timedelta(days=tpl.due_days))
    if extra_ctx:
        ctx.update(extra_ctx)
    cc = split_emails(tpl.cc)
    if tpl.include_global_cc:
        cc += split_emails(get_setting(db, "global_cc"))
    if tpl.include_department_cc and c.department_id:
        dept = db.get(models.Department, c.department_id)
        if dept:
            cc += split_emails(dept.cc_emails)
    if tpl.exclude_sender_from_cc:
        cc = minus(cc, [sender.email])
    cc = minus(cc, [c.email])
    return {
        "to": clean_email(c.email),
        "cc": join_emails(cc),
        "subject": render(tpl.subject, ctx),
        "body": render(tpl.body, ctx),
    }


# ---------------------------------------------------------------- audit + outbox

def audit(db: Session, user: models.User | None, action: str, detail: str = "", candidate_id: int | None = None):
    db.add(models.AuditLog(user_id=user.id if user else None, user_name=user.name if user else "HireModus (automatic)",
                           candidate_id=candidate_id, action=action, detail=detail))


def queue_job(db: Session, owner: models.User, kind: str, payload: dict, description: str = "",
              candidate_id: int | None = None, interview_id: int | None = None) -> models.OutboxJob:
    job = models.OutboxJob(owner_id=owner.id, kind=kind, payload=payload, description=description,
                           candidate_id=candidate_id, interview_id=interview_id)
    db.add(job)
    db.flush()
    if candidate_id and kind in ("send_mail", "reply_mail", "create_appointment", "update_appointment"):
        c = db.get(models.Candidate, candidate_id)
        recipients = split_emails(payload.get("to", "")) + split_emails(payload.get("required", ""))
        if c and c.email and clean_email(c.email) in recipients:
            from .aging import reset_clock
            reset_clock(c, owner)  # any message to the candidate restarts the aging clock
    if simulate(db):
        run_simulated(db, job)
    return job


def queue_mail(db: Session, owner: models.User, mail: dict, description: str, candidate_id=None, interview_id=None):
    if not mail.get("to"):
        raise ValueError("No email address on file")
    return queue_job(db, owner, "send_mail", mail, description, candidate_id, interview_id)


def queue_it_notice(db: Session, owner: models.User, c: models.Candidate, context_desc: str, links: str):
    it_to = get_setting(db, "it_emails")
    if not it_to.strip() or not links.strip():
        return None
    body = (
        "Hi,\n\n"
        f"The following SharePoint link(s) ({context_desc}) were just sent to a candidate as part of the "
        "interview process. Please grant them access.\n\n"
        f"{links.strip()}\n\n"
        f"Candidate: {c.first_name} {c.last_name}\nEmail: {c.email}\n\nThank you"
    )
    mail = {
        "to": join_emails(it_to),
        "cc": join_emails(minus(split_emails(get_setting(db, "it_cc")), [owner.email])),
        "subject": f"Access Request: SharePoint Link Sent to Candidate - {c.first_name} {c.last_name}".strip(),
        "body": body,
    }
    return queue_job(db, owner, "send_mail", mail, f"IT access request for {c.first_name} {c.last_name}", c.id)


# ---------------------------------------------------------------- job completion

def apply_job_result(db: Session, job: models.OutboxJob):
    """Side effects once the connector reports back."""
    if job.kind == "create_appointment" and job.interview_id:
        iv = db.get(models.Interview, job.interview_id)
        if iv:
            if job.status == "done":
                iv.outlook_entry_id = (job.result or {}).get("entry_id", "")
                iv.status = "scheduled"
            elif job.status == "failed":
                iv.status = "failed"
    if job.kind == "update_appointment" and job.interview_id and job.status == "done":
        iv = db.get(models.Interview, job.interview_id)
        if iv and (job.result or {}).get("entry_id"):
            iv.outlook_entry_id = job.result["entry_id"]


def run_simulated(db: Session, job: models.OutboxJob):
    """Stand-in for the Outlook connector so the app can be tried without Windows/Outlook."""
    job.status = "done"
    job.claimed_at = job.completed_at = datetime.utcnow()
    if job.kind == "create_appointment":
        job.result = {"entry_id": f"SIM-{job.id:06d}"}
    elif job.kind == "update_appointment":
        job.result = {"entry_id": job.payload.get("entry_id")}
    elif job.kind == "free_busy":
        start = date.fromisoformat(job.payload["start_date"])
        days = int(job.payload["days"])
        rng = random.Random(job.id)
        fb = {}
        for e in job.payload["emails"]:
            chunks = []
            for _ in range(days):
                s = ["0"] * 48
                for _ in range(rng.randint(1, 5)):  # a few random meetings per day
                    h = rng.randint(18, 34)
                    for k in range(h, min(48, h + rng.randint(1, 3))):
                        s[k] = "2"
                chunks.append("".join(s))
            fb[e] = {"start_date": start.isoformat(), "fb": "".join(chunks), "resolved": True}
        job.result = {"free_busy": fb, "me": job.payload.get("me_email", "")}
    elif job.kind == "reply_mail":
        job.result = {"simulated": True, "threaded": bool(job.payload.get("entry_id"))}
    else:
        job.result = {"simulated": True}
    apply_job_result(db, job)


def change_stage(db: Session, c: models.Candidate, stage_id: int | None, user: models.User | None = None):
    if stage_id == c.stage_id:
        return
    c.stage_id = stage_id
    c.stage_changed_at = datetime.utcnow()
    if get_setting(db, "aging_reset_on_stage_change") == "true":
        from .aging import reset_clock
        reset_clock(c, user)


def notify(db: Session, kind: str, title: str, body: str = "", link: str = "", permission: str = "candidates.view",
           user_id: int | None = None):
    db.add(models.Notification(kind=kind, title=title[:300], body=body, link=link, permission=permission, user_id=user_id))
