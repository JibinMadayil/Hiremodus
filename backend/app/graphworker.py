"""Background work for people whose mail goes through Microsoft 365: send their Outbox jobs and check their inboxes."""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models, msgraph, mailbox
from .perms import has
from .services import apply_job_result

REPLY_EVERY = timedelta(minutes=5)
_last_reply_check: dict[int, datetime] = {}


def graph_users(db: Session) -> list[models.User]:
    return [u for u in db.query(models.User).filter(models.User.active.is_(True))
            if has(u, "emails.send") and msgraph.transport_for(db, u) == "graph"]


def send_jobs(db: Session, users: list[models.User]) -> int:
    done = 0
    by_id = {u.id: u for u in users}
    if not by_id:
        return 0
    jobs = (db.query(models.OutboxJob).filter(models.OutboxJob.status == "queued", models.OutboxJob.owner_id.in_(list(by_id)))
            .order_by(models.OutboxJob.kind != "free_busy", models.OutboxJob.id).limit(25).all())
    for j in jobs:
        j.status, j.claimed_at, j.attempts = "claimed", datetime.utcnow(), (j.attempts or 0) + 1
        db.commit()
        try:
            j.result = msgraph.run_job(db, j, by_id[j.owner_id])
            j.status, j.error = "done", ""
        except Exception as e:  # stays visible in the Outbox; never retried automatically, so nothing is sent twice
            j.status, j.error = "failed", ("Microsoft 365: " + str(e))[:2000]
        j.completed_at = datetime.utcnow()
        apply_job_result(db, j)
        db.commit()
        done += 1
    return done


def check_replies(db: Session, users: list[models.User], force: bool = False) -> int:
    if not mailbox.enabled(db):
        return 0
    stored = 0
    now = datetime.utcnow()
    for u in users:
        if not force and now - _last_reply_check.get(u.id, datetime.min) < REPLY_EVERY:
            continue
        _last_reply_check[u.id] = now
        addresses = set(mailbox.watch_addresses(db, u))
        if not addresses:
            continue
        started = datetime.utcnow()
        try:
            msgs = msgraph.fetch_replies(db, u, mailbox.scan_since(db, u.graph_scan_at), addresses)
        except Exception:
            continue  # shown on the Microsoft 365 settings test; try again next round
        stored += mailbox.ingest(db, u, msgs, "graph")["stored"]
        u.graph_scan_at = started
        db.commit()
    return stored


def run_once(db: Session) -> None:
    if not msgraph.graph_on(db):
        return
    users = graph_users(db)
    send_jobs(db, users)
    check_replies(db, users)
