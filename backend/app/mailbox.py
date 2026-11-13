"""Candidate replies: which addresses an inbox is checked for, and storing what comes back.

Both the Outlook connector and Microsoft Graph hand messages to ingest(). A message is kept only when it comes from
an email address on a candidate's record; nothing else in a mailbox is stored."""
import base64
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import models
from .perms import dept_scope, has
from .services import audit, get_setting, notify, clean_email

UPLOAD_DIR = os.environ.get("HIREMODUS_UPLOAD_DIR", "./uploads")
MAIL_DIR = os.path.join(UPLOAD_DIR, "mail")
MAX_ATTACHMENT = 15 * 1024 * 1024
MAX_ATTACHMENTS = 20
OVERLAP = timedelta(minutes=10)  # re-read a little of the last window so nothing on the boundary is missed
ALERT_WINDOW = timedelta(hours=24)  # older replies found by the first look-back are stored quietly


def enabled(db: Session) -> bool:
    return get_setting(db, "replies_enabled") != "false"


def watch_addresses(db: Session, user: models.User) -> dict[str, int]:
    """Email address -> candidate id, for the candidates this person can work on."""
    scope = dept_scope(user)
    q = db.query(models.Candidate.id, models.Candidate.email, models.Candidate.department_id).filter(
        models.Candidate.email.isnot(None), models.Candidate.email != "", models.Candidate.anonymized_at.is_(None))
    out: dict[str, int] = {}
    for cid, email, dept in q.order_by(models.Candidate.id):
        if scope is not None and dept is not None and dept not in scope:
            continue
        e = clean_email(email)
        if e:
            out[e] = cid  # newest record wins when the same address is on two candidates
    return out


def scan_since(db: Session, last: datetime | None) -> datetime:
    if last:
        return last - OVERLAP
    days = int(get_setting(db, "replies_lookback_days") or 30)
    return datetime.utcnow() - timedelta(days=days)


QUOTE_START = re.compile(r"^(On .{5,200}wrote:|From: .+|-----Original Message-----|_{10,}|Sent from my )", re.I)


def preview_of(body: str) -> str:
    """The new part of a reply: stops at the quoted earlier message and skips quoted lines."""
    kept = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        if QUOTE_START.match(line.strip()):
            break
        if line.strip().startswith(">"):
            continue
        kept.append(line.strip())
    text = re.sub(r"\s+", " ", " ".join(kept)).strip()
    return (text[:297] + "...") if len(text) > 300 else text


def _safe_name(name: str) -> str:
    name = os.path.basename(name or "attachment").strip() or "attachment"
    return re.sub(r"[^A-Za-z0-9._ ()\-]", "_", name)[:150]


def _parse_time(v) -> datetime:
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    s = str(v or "").strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return datetime.utcnow()
    if d.tzinfo:
        d = d.astimezone(timezone.utc)
    return d.replace(tzinfo=None)


def recipients_for(db: Session, c: models.Candidate, mailbox_owner: models.User) -> list[models.User]:
    """People alerted about a reply: everyone working in the candidate's department, plus whoever's inbox had it."""
    users = {mailbox_owner.id: mailbox_owner}
    for u in db.query(models.User).filter(models.User.active.is_(True)):
        if not has(u, "candidates.view"):
            continue
        scope = dept_scope(u)
        if scope is None:
            continue  # admins see replies on the dashboard; they aren't alerted for every one
        if (c.department_id is None and has(u, "emails.send") and not scope) or (c.department_id in scope):
            users[u.id] = u
    return list(users.values())


def ingest(db: Session, owner: models.User, messages: list[dict], via: str) -> dict:
    """Store candidate replies found in owner's inbox. Returns counts."""
    watch = watch_addresses(db, owner)
    stored = copies = skipped = 0
    for m in messages:
        sender = clean_email(m.get("from") or "")
        cid = watch.get(sender)
        if not cid:
            skipped += 1
            continue
        received = _parse_time(m.get("received_at"))
        mid = (m.get("message_id") or "").strip()[:500]
        if not mid:
            mid = "hm:" + hashlib.sha1(f"{sender}|{m.get('subject','')}|{received.isoformat()}".encode()).hexdigest()
        copy = {"via": via, "id": str(m.get("entry_id") or m.get("graph_id") or "")}
        existing = db.query(models.CandidateEmail).filter_by(message_id=mid).first()
        if existing:
            cp = dict(existing.copies or {})
            if str(owner.id) not in cp:
                cp[str(owner.id)] = copy
                existing.copies = cp
                copies += 1
            continue
        c = db.get(models.Candidate, cid)
        e = models.CandidateEmail(
            candidate_id=cid, message_id=mid, from_addr=sender, from_name=(m.get("from_name") or "")[:300],
            to_addrs=(m.get("to") or "")[:4000], cc_addrs=(m.get("cc") or "")[:4000], subject=(m.get("subject") or "")[:500],
            received_at=received, body=(m.get("body") or "")[:200000], preview=preview_of(m.get("body") or ""),
            copies={str(owner.id): copy}, read_by=[], attachments=[])
        db.add(e)
        db.flush()
        saved = []
        for a in (m.get("attachments") or [])[:MAX_ATTACHMENTS]:
            try:
                data = base64.b64decode(a.get("content_b64") or "")
            except Exception:
                continue
            if not data or len(data) > MAX_ATTACHMENT:
                saved.append({"name": _safe_name(a.get("name")), "size": a.get("size") or len(data), "file": "", "skipped": True})
                continue
            folder = os.path.join(MAIL_DIR, str(e.id))
            os.makedirs(folder, exist_ok=True)
            fname = f"{len(saved)}_{_safe_name(a.get('name'))}"
            with open(os.path.join(folder, fname), "wb") as fh:
                fh.write(data)
            saved.append({"name": _safe_name(a.get("name")), "size": len(data), "file": fname})
        e.attachments = saved
        stored += 1
        audit(db, None, "email_reply_received", f"{e.subject or '(no subject)'} (in {owner.name}'s inbox)", candidate_id=cid)
        if c and received > datetime.utcnow() - ALERT_WINDOW:
            # a reply is contact: the aging clock restarts from when they wrote
            if not c.clock_started_at or c.clock_started_at < received:
                c.clock_started_at = received
                c.aging_grace_until = None
                c.aging_alerted_for = None
            name = f"{c.first_name} {c.last_name}".strip() or sender
            for u in recipients_for(db, c, owner):
                notify(db, "reply", f"{name} replied: {e.subject or '(no subject)'}", e.preview[:200], f"/candidates/{cid}", user_id=u.id)
    return {"stored": stored, "copies": copies, "skipped": skipped}


def unread_counts(db: Session, user: models.User, candidate_ids: list[int] | None = None) -> dict[int, int]:
    q = db.query(models.CandidateEmail.candidate_id, models.CandidateEmail.read_by)
    if candidate_ids is not None:
        if not candidate_ids:
            return {}
        q = q.filter(models.CandidateEmail.candidate_id.in_(candidate_ids))
    out: dict[int, int] = {}
    for cid, read_by in q:
        if user.id not in (read_by or []):
            out[cid] = out.get(cid, 0) + 1
    return out


def email_out(e: models.CandidateEmail, user: models.User, full: bool = False) -> dict:
    d = {"id": e.id, "candidate_id": e.candidate_id, "from": e.from_addr, "from_name": e.from_name, "subject": e.subject,
         "received_at": e.received_at.isoformat() + "Z", "preview": e.preview, "unread": user.id not in (e.read_by or []),
         "attachments": [{"index": i, "name": a["name"], "size": a.get("size", 0), "available": bool(a.get("file"))}
                         for i, a in enumerate(e.attachments or [])],
         "in_my_inbox": str(user.id) in (e.copies or {})}
    if full:
        d.update(body=e.body, to=e.to_addrs, cc=e.cc_addrs)
    return d


def quote(e: models.CandidateEmail) -> str:
    when = e.received_at.strftime("%Y-%m-%d %H:%M") + " UTC"
    sender = f"{e.from_name} <{e.from_addr}>" if e.from_name else e.from_addr
    lines = "\n".join("> " + ln for ln in (e.body or "").replace("\r\n", "\n").split("\n"))
    return f"\n\nOn {when}, {sender} wrote:\n{lines}"


def delete_files(email_ids: list[int]):
    import shutil
    for eid in email_ids:
        shutil.rmtree(os.path.join(MAIL_DIR, str(eid)), ignore_errors=True)
