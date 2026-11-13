"""Aging rules: alert after N days without contact, automatic rejection after M days.

The clock starts when a candidate is added and restarts whenever HireModus emails or invites them, or someone
clicks "Mark as contacted". A booked interview in the future pauses it; once the interview date passes, the clock
counts again from the interview day. Imported candidates start from the latest date in the spreadsheet."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date

from sqlalchemy.orm import Session

from . import models
from .services import (TZ, get_setting, set_setting, local_now, split_emails, join_emails, minus, render,
                       build_template_email, queue_mail, fmt_date, audit)

ACTIVE_IV = ("sending", "scheduled")


def to_utc(local_naive: datetime) -> datetime:
    return local_naive.replace(tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)


def to_local(utc_naive: datetime) -> datetime:
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(TZ).replace(tzinfo=None)


def cfg(db: Session) -> dict:
    g = lambda k: get_setting(db, k)
    return {
        "enabled": g("aging_enabled") == "true",
        "alert_days": int(g("aging_alert_days") or 30),
        "reject_days": int(g("aging_reject_days") or 45),
        "auto_reject": g("aging_auto_reject") == "true",
        "recipients": split_emails(g("aging_recipients")),
        "sender": g("aging_sender_email").strip().lower(),
        "run_time": g("aging_run_time") or "08:00",
        "cc_department": g("aging_cc_department") == "true",
        "cc_last_contact": g("aging_cc_last_contact") == "true",
        "reset_on_stage_change": g("aging_reset_on_stage_change") == "true",
        "grace_days": int(g("aging_import_grace_days") or 7),
        "mode": g("aging_alert_mode") or "daily",
    }


def reset_clock(c: models.Candidate, user: models.User | None):
    c.clock_started_at = datetime.utcnow()
    c.aging_grace_until = None
    c.aging_alerted_for = None
    if user:
        c.last_contact_by = user.id


def interviews_by_candidate(db: Session, ids: list[int] | None = None) -> dict[int, list[models.Interview]]:
    q = db.query(models.Interview).filter(models.Interview.status.in_(ACTIVE_IV))
    if ids is not None:
        if not ids:
            return {}
        q = q.filter(models.Interview.candidate_id.in_(ids))
    out = defaultdict(list)
    for iv in q:
        out[iv.candidate_id].append(iv)
    return out


def evaluate(c: models.Candidate, stage: models.Stage | None, ivs: list[models.Interview], conf: dict,
             now_local: datetime | None = None) -> dict | None:
    """Days in stage and status for one candidate, or None if the stage doesn't count."""
    if not conf["enabled"] or not stage or not stage.aging_enabled or stage.kind != "open":
        return None
    now_local = now_local or local_now()
    alert = stage.alert_days or conf["alert_days"]
    reject = stage.reject_days or conf["reject_days"]
    upcoming = [iv for iv in ivs if iv.start > now_local]
    base_local = to_local(c.clock_started_at or c.created_at)
    past = [iv.end for iv in ivs if iv.end <= now_local]
    if past:
        base_local = max(base_local, max(past))
    days = (now_local.date() - base_local.date()).days + 1
    reject_on = base_local.date() + timedelta(days=reject - 1)
    if c.aging_grace_until and c.aging_grace_until > reject_on:
        reject_on = c.aging_grace_until
    if c.aging_exempt:
        status = "exempt"
    elif upcoming:
        status = "paused"
    elif days >= reject:
        status = "due" if now_local.date() >= reject_on else "grace"
    elif days >= alert:
        status = "alert"
    else:
        status = "ok"
    return {"days": days, "status": status, "alert_days": alert, "reject_days": reject,
            "reject_on": reject_on.isoformat() if status not in ("exempt", "paused") else None,
            "since": base_local.date().isoformat(),
            "next_interview": min(iv.start for iv in upcoming).isoformat() if upcoming else None}


def area_of(c: models.Candidate, stage: models.Stage, depts: dict) -> tuple[str, int | None]:
    d = depts.get(c.department_id)
    if d:
        return d.name, d.id
    return stage.name, None


def snapshot(db: Session, user: models.User | None = None, department_id: int | None = None) -> list[tuple[models.Candidate, models.Stage, dict]]:
    conf = cfg(db)
    if not conf["enabled"]:
        return []
    stages = {s.id: s for s in db.query(models.Stage).filter(models.Stage.aging_enabled.is_(True))}
    if not stages:
        return []
    q = db.query(models.Candidate).filter(models.Candidate.stage_id.in_(list(stages)))
    if user is not None:
        from .perms import limit_full
        q = limit_full(q, db, user)
    if department_id:
        q = q.filter(models.Candidate.department_id == department_id)
    cands = q.all()
    ivs = interviews_by_candidate(db, [c.id for c in cands])
    now_local = local_now()
    out = []
    for c in cands:
        ev = evaluate(c, stages.get(c.stage_id), ivs.get(c.id, []), conf, now_local)
        if ev:
            out.append((c, stages[c.stage_id], ev))
    return out


def kpis(db: Session, user: models.User | None = None, department_id: int | None = None) -> dict:
    depts = {d.id: d for d in db.query(models.Department)}
    rows = snapshot(db, user, department_id)
    by_area = defaultdict(lambda: {"over": 0, "due_soon": 0, "buckets": [0, 0, 0, 0]})
    conf = cfg(db)
    today = local_now().date()
    for c, st, ev in rows:
        name, _ = area_of(c, st, depts)
        a = by_area[name]
        d = ev["days"]
        a["buckets"][0 if d <= 15 else 1 if d < ev["alert_days"] else 2 if d < ev["reject_days"] else 3] += 1
        if ev["status"] in ("alert", "due", "grace"):
            a["over"] += 1
        if ev["reject_on"] and ev["status"] in ("alert", "grace", "due") and date.fromisoformat(ev["reject_on"]) <= today + timedelta(days=7):
            a["due_soon"] += 1
    month_start = datetime(today.year, today.month, 1)
    auto = db.query(models.AuditLog).filter(models.AuditLog.action == "auto_rejected", models.AuditLog.at >= to_utc(month_start)).count()
    return {
        "enabled": conf["enabled"], "alert_days": conf["alert_days"], "reject_days": conf["reject_days"],
        "over_total": sum(a["over"] for a in by_area.values()),
        "due_soon_total": sum(a["due_soon"] for a in by_area.values()),
        "auto_rejected_month": auto,
        "areas": [{"area": k, **v} for k, v in sorted(by_area.items())],
    }


# ---------------------------------------------------------------- the daily run

def due_now(db: Session) -> bool:
    conf = cfg(db)
    if not conf["enabled"]:
        return False
    now = local_now()
    h, m = (conf["run_time"] or "08:00").split(":")
    return get_setting(db, "aging_last_run") != now.date().isoformat() and now.time() >= now.replace(hour=int(h), minute=int(m)).time()


def run(db: Session, force: bool = False) -> dict:
    conf = cfg(db)
    result = {"rejected": [], "alert_emails": 0, "alerted": 0, "warnings": []}
    if not conf["enabled"] and not force:
        return result
    sender = db.query(models.User).filter(models.User.email == conf["sender"], models.User.active.is_(True)).first() if conf["sender"] else None
    if not sender:
        result["warnings"].append("No active user matches the alert sender email, so no emails were queued.")
    depts = {d.id: d for d in db.query(models.Department)}
    users = {u.id: u for u in db.query(models.User)}
    reject_stage = db.query(models.Stage).filter(models.Stage.kind == "rejected", models.Stage.active.is_(True)).order_by(models.Stage.sort).first()
    today = local_now().date()

    alerts = defaultdict(list)  # area -> [(c, stage, ev)]
    for c, st, ev in snapshot(db):
        if ev["status"] == "due" and conf["auto_reject"] and reject_stage:
            name = f"{c.first_name} {c.last_name}".strip()
            old = st.name
            c.stage_id = reject_stage.id
            c.stage_changed_at = datetime.utcnow()
            emailed = False
            if sender and c.email and reject_stage.entry_template_id:
                tpl = db.get(models.EmailTemplate, reject_stage.entry_template_id)
                if tpl and tpl.active:
                    queue_mail(db, sender, build_template_email(db, tpl, c, sender), f"Automatic rejection: {name}", c.id)
                    emailed = True
            audit(db, None, "auto_rejected", f"{ev['days']} days in {old} without contact{' (rejection email queued)' if emailed else ''}", c.id)
            result["rejected"].append({"id": c.id, "name": name, "from": old, "days": ev["days"]})
            continue
        if ev["status"] in ("alert", "due", "grace"):
            if conf["mode"] == "new" and c.aging_alerted_for == (c.clock_started_at or c.created_at):
                continue
            alerts[area_of(c, st, depts)].append((c, st, ev))

    tpl = db.query(models.EmailTemplate).filter_by(key="aging_alert").first()
    for (area, dept_id), items in sorted(alerts.items(), key=lambda x: x[0][0]):
        lines = []
        cc = []
        for c, st, ev in sorted(items, key=lambda x: -x[2]["days"]):
            when = fmt_date(date.fromisoformat(ev["reject_on"])) if ev["reject_on"] else ""
            note = f"automatic rejection on {when}" if conf["auto_reject"] and when else ""
            lines.append(f"- {c.first_name} {c.last_name} ({c.email or 'no email'}), {st.name}, {ev['days']} days since last contact"
                         + (f", {note}" if note else ""))
            c.aging_alerted_for = c.clock_started_at or c.created_at
            if conf["cc_last_contact"] and c.last_contact_by in users:
                cc.append(users[c.last_contact_by].email)
        if conf["cc_department"] and dept_id:
            cc += split_emails(depts[dept_id].cc_emails)
        result["alerted"] += len(items)
        ctx = {"area": area, "count": str(len(items)), "alert_days": str(conf["alert_days"]),
               "reject_days": str(conf["reject_days"]), "candidate_list": "\n".join(lines),
               "company": get_setting(db, "company_name"), "sender_name": sender.name if sender else ""}
        subject = render(tpl.subject if tpl else "{{count}} candidate(s) in {{area}} for more than {{alert_days}} days", ctx)
        body = render(tpl.body if tpl else "{{candidate_list}}", ctx)
        db.add(models.Notification(kind="aging", title=subject, body="\n".join(lines), link="/candidates?aging=over"))
        if sender and conf["recipients"]:
            cc_final = minus(split_emails(join_emails(cc)), conf["recipients"])
            queue_mail(db, sender, {"to": join_emails(conf["recipients"]), "cc": join_emails(cc_final),
                                    "subject": subject, "body": body}, f"Aging alert: {area}")
            result["alert_emails"] += 1
    if result["rejected"]:
        names = ", ".join(r["name"] for r in result["rejected"])
        title = f"{len(result['rejected'])} candidate(s) rejected automatically"
        db.add(models.Notification(kind="auto_rejected", title=title, body=names, link="/candidates"))
        extra = split_emails(get_setting(db, "notify_auto_rejected_emails"))
        if extra and sender:
            lines = "\n".join(f"- {r['name']}: {r['days']} days in {r['from']} without contact" for r in result["rejected"])
            queue_mail(db, sender, {"to": join_emails(extra), "cc": "", "subject": title,
                                    "body": f"HireModus rejected these candidates automatically today:\n\n{lines}\n\nThank you"}, title)
    set_setting(db, "aging_last_run", today.isoformat())
    db.commit()
    return result


def initial_clock(c: models.Candidate, dates_local: list[datetime], conf: dict, now_local: datetime):
    """Clock for an imported/migrated candidate: latest spreadsheet date, plus a grace period if already past the limit."""
    past = [d for d in dates_local if d and d <= now_local]
    if past:
        base = max(past)
        c.clock_started_at = to_utc(base)
        days = (now_local.date() - base.date()).days + 1
        if days >= conf["reject_days"]:
            c.aging_grace_until = now_local.date() + timedelta(days=conf["grace_days"])
    elif not c.clock_started_at:
        c.clock_started_at = datetime.utcnow()
