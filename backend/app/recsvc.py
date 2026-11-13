"""Test recordings: where they live, and deleting them at midnight (office time) on the day of the test."""
import os
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import models
from .services import TZ

UPLOAD_DIR = os.environ.get("HIREMODUS_UPLOAD_DIR", "./uploads")
REC_DIR = os.path.join(UPLOAD_DIR, "recordings")


def next_local_midnight_utc(at_utc: datetime | None = None) -> datetime:
    """The UTC moment of the coming midnight in the office time zone (naive UTC, like the rest of the DB)."""
    at_utc = at_utc or datetime.utcnow()
    local = at_utc.replace(tzinfo=timezone.utc).astimezone(TZ)
    midnight_local = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tzinfo=TZ)
    return midnight_local.astimezone(timezone.utc).replace(tzinfo=None)


def recording_path(assignment_id: int, rec_id: int, kind: str) -> str:
    folder = os.path.join(REC_DIR, str(assignment_id))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{rec_id}-{kind}.webm")


def delete_due(db: Session) -> int:
    n = 0
    for r in db.query(models.Recording).filter(models.Recording.deleted.is_(False),
                                                models.Recording.delete_at <= datetime.utcnow()):
        try:
            if r.path and os.path.exists(r.path):
                os.remove(r.path)
        except OSError:
            continue  # try again next round
        r.deleted = True
        r.path = ""
        n += 1
    for sn in db.query(models.Snapshot).filter(models.Snapshot.deleted.is_(False), models.Snapshot.delete_at <= datetime.utcnow()):
        try:
            if sn.path and os.path.exists(sn.path):
                os.remove(sn.path)
        except OSError:
            continue
        sn.deleted, sn.path = True, ""
        n += 1
    return n


def remove_assignment_files(assignment_id: int):
    for folder in (os.path.join(REC_DIR, str(assignment_id)), os.path.join(UPLOAD_DIR, str(assignment_id))):
        shutil.rmtree(folder, ignore_errors=True)
