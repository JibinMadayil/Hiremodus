"""Slot finding, driven by an interview template."""
from datetime import datetime, timedelta, date

from . import models
from .services import split_emails, minus

STEP_MIN = 30
ME = "__me__"


def hm(text: str) -> tuple[int, int]:
    h, m = (text or "09:00").split(":")
    return int(h), int(m)


class FreeBusy:
    def __init__(self, result: dict | None):
        self.data = (result or {}).get("free_busy", {}) or {}

    def known(self, email: str) -> bool:
        d = self.data.get(email)
        return bool(d and d.get("resolved") and d.get("fb"))

    def is_free(self, email: str, start: datetime, end: datetime) -> bool:
        d = self.data.get(email)
        if not d or not d.get("fb"):
            return True  # no free/busy data means we can't prove they're busy
        base = datetime.fromisoformat(d["start_date"]) if "T" in d["start_date"] else datetime.combine(
            date.fromisoformat(d["start_date"]), datetime.min.time())
        fb = d["fb"]
        first = int((start - base).total_seconds() // 60) // STEP_MIN
        last = (int((end - base).total_seconds() // 60) - 1) // STEP_MIN
        for k in range(first, last + 1):
            if 0 <= k < len(fb) and fb[k] != "0":
                return False
        return True


def search_range(tpl: models.InterviewTemplate, now: datetime, from_date: date | None = None) -> tuple[date, date]:
    start = from_date or (now.date() + timedelta(days=tpl.search_offset_days or 0))
    end = start + timedelta(days=tpl.search_window_days or 14)
    return start, end


def emails_to_check(tpl: models.InterviewTemplate) -> list[str]:
    out = split_emails(tpl.required_emails) + split_emails(tpl.flex_emails)
    if tpl.check_own_calendar:
        out.append(ME)
    return out


def classify(tpl: models.InterviewTemplate, fb: FreeBusy, start: datetime, end: datetime) -> dict:
    required = split_emails(tpl.required_emails)
    flex = split_emails(tpl.flex_emails)
    busy_required = [e for e in required if not fb.is_free(e, start, end)]
    flex_free = [e for e in flex if fb.is_free(e, start, end)]
    flex_busy = [e for e in flex if e not in flex_free]
    me_free = fb.is_free(ME, start, end) if tpl.check_own_calendar else True
    unknown = [e for e in required + flex if not fb.known(e)] if fb.data else []
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "required": required + flex_free,
        "optional": split_emails(tpl.optional_emails) + flex_busy,
        "busy_required": busy_required,
        "flex_free": flex_free,
        "flex_busy": flex_busy,
        "me_free": me_free,
        "unknown": unknown,
    }


def find_slots(tpl: models.InterviewTemplate, fb: FreeBusy, now: datetime, holidays: set[date],
               from_date: date | None = None, limit: int | None = None) -> list[dict]:
    limit = limit or tpl.slot_options or 5
    d0, d1 = search_range(tpl, now, from_date)
    dur = timedelta(minutes=tpl.duration_min)
    flex = split_emails(tpl.flex_emails)
    preferred = [e for e in split_emails(tpl.flex_preferred_emails) if e in flex]
    tiers = [1, 2] if flex else [2]
    found: list[dict] = []
    seen: set[str] = set()
    sh, sm = hm(tpl.day_start)
    eh, em = hm(tpl.day_end)
    for tier in tiers:
        day = d0
        while day <= d1 and len(found) < limit:
            if day.isoweekday() in (tpl.weekdays or [1, 2, 3, 4, 5]) and day not in holidays:
                slot = datetime.combine(day, datetime.min.time()).replace(hour=sh, minute=sm)
                day_end = datetime.combine(day, datetime.min.time()).replace(hour=eh, minute=em)
                if slot < now:
                    # next half-hour boundary after now
                    nxt = now.replace(second=0, microsecond=0)
                    nxt += timedelta(minutes=(STEP_MIN - nxt.minute % STEP_MIN) % STEP_MIN or STEP_MIN)
                    slot = max(slot, nxt)
                while slot + dur <= day_end and len(found) < limit:
                    key = slot.isoformat()
                    if key not in seen:
                        info = classify(tpl, fb, slot, slot + dur)
                        ok = not info["busy_required"] and info["me_free"]
                        if ok and flex:
                            if tier == 1:
                                ok = all(e in info["flex_free"] for e in preferred) and \
                                    len(info["flex_free"]) >= max(1, tpl.flex_min_free)
                            else:
                                ok = len(info["flex_free"]) >= max(1, tpl.flex_min_free)
                        if ok:
                            info["tier"] = tier
                            found.append(info)
                            seen.add(key)
                    slot += timedelta(minutes=STEP_MIN)
            day += timedelta(days=1)
    found.sort(key=lambda s: (s["tier"], s["start"]))
    return found


def evaluate(tpl: models.InterviewTemplate, fb: FreeBusy, start: datetime, now: datetime,
             holidays: set[date]) -> dict:
    end = start + timedelta(minutes=tpl.duration_min)
    info = classify(tpl, fb, start, end)
    warnings = []
    if start < now:
        warnings.append("That time is in the past.")
    if tpl.search_offset_days and start.date() < now.date() + timedelta(days=tpl.search_offset_days):
        warnings.append(f"This is earlier than the recommended {tpl.search_offset_days} days out.")
    if start.isoweekday() not in (tpl.weekdays or []):
        warnings.append("This day of the week is outside the template's allowed days.")
    if start.date() in holidays:
        warnings.append("That date is on the holiday list.")
    if not info["me_free"]:
        warnings.append("You already have something on your calendar at that time.")
    for e in info["busy_required"]:
        warnings.append(f"{e.split('@')[0]} does not appear to be free at that time. Please confirm with them directly.")
    flex = split_emails(tpl.flex_emails)
    if flex and not info["flex_free"]:
        warnings.append("None of the rotating interviewers are free; they'll all be added as optional.")
    info["warnings"] = warnings
    return info


def no_check_attendees(tpl: models.InterviewTemplate, start: datetime) -> dict:
    """Attendees when the calendar isn't checked at all: every flex person goes in as required."""
    end = start + timedelta(minutes=tpl.duration_min)
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "required": split_emails(tpl.required_emails) + split_emails(tpl.flex_emails),
        "optional": split_emails(tpl.optional_emails),
        "busy_required": [], "flex_free": [], "flex_busy": [], "me_free": True, "unknown": [],
        "warnings": ["Calendars were not checked."],
    }
