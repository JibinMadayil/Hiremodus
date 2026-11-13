"""HireModus Outlook Connector

Runs on a recruiter's Windows PC next to desktop Outlook. It asks the HireModus server for work
(emails, meeting invites, reschedules, free/busy checks, replies) and does it through this user's own Outlook.
Every few minutes it also looks in the Inbox for emails from candidates and passes only those to HireModus.
Nothing is stored here except config.json.

Run with start_connector.bat, or:  python hiremodus_connector.py
"""
import base64
import json
import logging
import tempfile
import os
import platform
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

VERSION = "1.1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(HERE, "connector.log"), encoding="utf-8")],
)
log = logging.getLogger("hiremodus")

try:
    import requests
    import pythoncom
    import win32com.client
except ImportError:
    print("Missing packages. Run:  python -m pip install -r requirements.txt")
    raise

OL_MAIL, OL_APPT = 0, 1
OL_INBOX = 6
OL_MAILITEM_CLASS = 43
OL_BY_VALUE = 1
PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001F"
OL_MEETING, OL_MEETING_CANCELED = 1, 5


def local_to_utc(d: datetime) -> datetime:
    """Outlook gives times as this PC's local wall clock (pywin32 may label them UTC; the clock value is local)."""
    naive = d.replace(tzinfo=None)
    return datetime.fromtimestamp(time.mktime(naive.timetuple()), tz=timezone.utc).replace(tzinfo=None)


def utc_to_local(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def parse(dt: str) -> datetime:
    # interview times are office wall-clock times; Outlook treats a plain date value as local time
    return datetime.fromisoformat(dt).replace(tzinfo=None)


class Outlook:
    def __init__(self):
        pythoncom.CoInitialize()
        self.app = win32com.client.Dispatch("Outlook.Application")
        self.ns = self.app.GetNamespace("MAPI")

    def my_address(self) -> str:
        try:
            u = self.ns.CurrentUser.AddressEntry
            ex = u.GetExchangeUser()
            if ex is not None and ex.PrimarySmtpAddress:
                return ex.PrimarySmtpAddress
            return u.Address
        except Exception:
            return ""

    def my_name(self) -> str:
        try:
            return self.ns.CurrentUser.Name
        except Exception:
            return ""

    @staticmethod
    def _unresolved(item) -> str:
        bad = [r.Name for r in item.Recipients if not r.Resolved]
        return "; ".join(bad) or "unknown recipient"

    def send_mail(self, p: dict) -> dict:
        m = self.app.CreateItem(OL_MAIL)
        m.To = p.get("to", "")
        m.CC = p.get("cc", "")
        m.Subject = p.get("subject", "")
        m.Body = p.get("body", "")
        if not m.Recipients.ResolveAll():
            raise RuntimeError("Outlook could not resolve: " + self._unresolved(m))
        m.Send()
        return {}

    def reply_mail(self, p: dict) -> dict:
        """Answer a candidate's email. Uses Outlook's own Reply when the message is in this Inbox, so it stays in the thread."""
        if p.get("entry_id"):
            try:
                orig = self.ns.GetItemFromID(p["entry_id"])
                r = orig.Reply()
                r.Body = p.get("body", "") + "\r\n\r\n" + (r.Body or "")
                if p.get("cc"):
                    r.CC = p["cc"]
                if not r.Recipients.ResolveAll():
                    raise RuntimeError("Outlook could not resolve: " + self._unresolved(r))
                r.Send()
                return {"threaded": True}
            except RuntimeError:
                raise
            except Exception:
                pass  # the original was moved or deleted: send a new email instead
        self.send_mail({"to": p.get("to", ""), "cc": p.get("cc", ""), "subject": p.get("subject", ""),
                        "body": p.get("body", "") + p.get("quoted", "")})
        return {"threaded": False}

    @staticmethod
    def _sender(item) -> str:
        try:
            if (item.SenderEmailType or "").upper() == "EX":
                ex = item.Sender.GetExchangeUser()
                if ex is not None and ex.PrimarySmtpAddress:
                    return ex.PrimarySmtpAddress.lower()
                return (item.Sender.PropertyAccessor.GetProperty(PR_SMTP_ADDRESS) or "").lower()
            return (item.SenderEmailAddress or "").lower()
        except Exception:
            return ""

    @staticmethod
    def _recipients(item, kind: int) -> str:
        out = []
        try:
            for r in item.Recipients:
                if r.Type == kind:
                    addr = r.Address or ""
                    try:
                        addr = r.PropertyAccessor.GetProperty(PR_SMTP_ADDRESS) or addr
                    except Exception:
                        pass
                    out.append(addr)
        except Exception:
            pass
        return "; ".join(out)

    def scan_inbox(self, since_utc: datetime, addresses: set, max_bytes: int):
        """Yields candidate emails received since `since_utc`, newest first. Other mail is skipped without being read."""
        inbox = self.ns.GetDefaultFolder(OL_INBOX)
        items = inbox.Items
        items.Sort("[ReceivedTime]", True)
        since_local = utc_to_local(since_utc)
        item = items.GetFirst()
        seen = 0
        while item is not None and seen < 5000:
            seen += 1
            try:
                if item.Class == OL_MAILITEM_CLASS:
                    received = item.ReceivedTime.replace(tzinfo=None)
                    if received < since_local:
                        break
                    sender = self._sender(item)
                    if sender in addresses:
                        yield self._message(item, sender, received, max_bytes)
            except Exception as e:
                log.warning("Skipped one Inbox item: %s", e)
            item = items.GetNext()

    def _message(self, item, sender: str, received_local: datetime, max_bytes: int) -> dict:
        try:
            mid = item.PropertyAccessor.GetProperty(PR_INTERNET_MESSAGE_ID) or ""
        except Exception:
            mid = ""
        atts = []
        try:
            for a in item.Attachments:
                if a.Type != OL_BY_VALUE:
                    continue
                if a.Size > max_bytes:
                    atts.append({"name": a.FileName, "size": a.Size, "content_b64": ""})
                    continue
                tmp = os.path.join(tempfile.gettempdir(), f"hm_{os.getpid()}_{a.Index}_{a.FileName}")
                try:
                    a.SaveAsFile(tmp)
                    with open(tmp, "rb") as fh:
                        atts.append({"name": a.FileName, "size": a.Size, "content_b64": base64.b64encode(fh.read()).decode()})
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        except Exception as e:
            log.warning("Couldn't read attachments of '%s': %s", item.Subject, e)
        return {"entry_id": item.EntryID, "message_id": mid, "from": sender, "from_name": item.SenderName or "",
                "to": self._recipients(item, 1), "cc": self._recipients(item, 2), "subject": item.Subject or "",
                "received_at": local_to_utc(received_local).isoformat() + "Z", "body": item.Body or "", "attachments": atts}

    def create_appointment(self, p: dict) -> dict:
        a = self.app.CreateItem(OL_APPT)
        a.Subject = p["subject"]
        a.Start = parse(p["start"])
        a.End = parse(p["end"])
        a.Location = p.get("location", "")
        a.MeetingStatus = OL_MEETING
        a.RequiredAttendees = p.get("required", "")
        a.OptionalAttendees = p.get("optional", "")
        a.Body = p.get("body", "")
        a.Recipients.ResolveAll()
        a.Save()
        entry_id = a.EntryID
        a.Send()
        return {"entry_id": entry_id}

    def _get(self, entry_id: str):
        try:
            return self.ns.GetItemFromID(entry_id)
        except Exception:
            raise RuntimeError("The original meeting wasn't found in this Outlook calendar "
                               "(it may have been deleted, or it was booked from someone else's Outlook).")

    def update_appointment(self, p: dict) -> dict:
        a = self._get(p["entry_id"])
        a.Start = parse(p["start"])
        a.End = parse(p["end"])
        a.MeetingStatus = OL_MEETING
        a.Save()
        a.Send()
        a.Save()
        return {"entry_id": a.EntryID}

    def cancel_appointment(self, p: dict) -> dict:
        a = self._get(p["entry_id"])
        a.MeetingStatus = OL_MEETING_CANCELED
        a.Save()
        a.Send()
        try:
            a.Delete()
        except Exception:
            pass
        return {}

    def free_busy(self, p: dict) -> dict:
        start = datetime.fromisoformat(p["start_date"])
        days = int(p["days"])
        me = self.my_address()
        out = {}
        for email in p["emails"]:
            addr = me if email == "__me__" else email
            entry = {"start_date": start.date().isoformat(), "fb": "", "resolved": False}
            try:
                r = self.ns.CreateRecipient(addr)
                r.Resolve()
                if r.Resolved:
                    fb = r.FreeBusy(start, 30, True) or ""
                    # FreeBusy covers a fixed period; ask again if the window is longer
                    while len(fb) < days * 48:
                        more = r.FreeBusy(start + timedelta(minutes=30 * len(fb)), 30, True) or ""
                        if not more:
                            break
                        fb += more
                    entry.update(fb=fb[: days * 48], resolved=True)
            except Exception as e:
                entry["error"] = str(e)[:200]
            out[email] = entry
        return {"free_busy": out, "me": me}


def load_config() -> dict:
    if not os.path.exists(CONFIG):
        sys.exit("config.json is missing. Download the connector again from HireModus > My Outlook.")
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["server_url"] = cfg["server_url"].rstrip("/")
    return cfg


def check_replies(s, url: str, ol: "Outlook") -> int:
    """Ask HireModus which candidate addresses to look for, scan the Inbox, and send back only those emails."""
    w = s.get(f"{url}/api/connector/watch", timeout=30)
    w.raise_for_status()
    w = w.json()
    if not w.get("enabled") or not w.get("addresses"):
        return int(w.get("interval_seconds") or 300)
    started = datetime.now(timezone.utc).replace(tzinfo=None)
    since = datetime.fromisoformat(w["since"].replace("Z", "+00:00")).replace(tzinfo=None)
    batch, found = [], 0
    for msg in ol.scan_inbox(since, set(a.lower() for a in w["addresses"]), int(w.get("max_attachment_bytes") or 15 * 1024 * 1024)):
        batch.append(msg)
        found += 1
        if len(batch) >= 5:
            s.post(f"{url}/api/connector/replies", json={"scanned_at": started.isoformat() + "Z", "messages": batch, "final": False},
                   timeout=120).raise_for_status()
            batch = []
    s.post(f"{url}/api/connector/replies", json={"scanned_at": started.isoformat() + "Z", "messages": batch, "final": True},
           timeout=120).raise_for_status()
    if found:
        log.info("Found  %d candidate email(s) in the Inbox", found)
    return int(w.get("interval_seconds") or 300)


def main():
    cfg = load_config()
    s = requests.Session()
    s.headers["X-Connector-Key"] = cfg["connector_key"]
    s.headers["User-Agent"] = f"HireModusConnector/{VERSION}"
    if cfg.get("verify_tls") is False:
        s.verify = False
    poll = max(2, int(cfg.get("poll_seconds", 5)))
    url = cfg["server_url"]

    ol = Outlook()
    log.info("HireModus Outlook Connector %s", VERSION)
    log.info("Server: %s", url)
    log.info("Outlook user: %s <%s>", ol.my_name(), ol.my_address())
    log.info("Leave this window open. Close it to stop sending.")

    last_beat = 0.0
    next_replies = 0.0
    backoff = poll
    while True:
        try:
            if time.time() - last_beat > 30:
                r = s.post(f"{url}/api/connector/heartbeat", json={
                    "version": VERSION, "outlook_user": ol.my_name(), "outlook_email": ol.my_address(),
                    "machine": platform.node()}, timeout=20)
                if r.status_code == 401:
                    log.error("The server rejected this connector key. Download a fresh copy from HireModus > My Outlook.")
                    time.sleep(60)
                    continue
                r.raise_for_status()
                last_beat = time.time()

            if time.time() >= next_replies:
                try:
                    next_replies = time.time() + check_replies(s, url, ol)
                except requests.RequestException:
                    raise
                except Exception as e:
                    log.warning("Inbox check failed: %s", e)
                    next_replies = time.time() + 300

            r = s.get(f"{url}/api/connector/jobs", timeout=30)
            r.raise_for_status()
            for job in r.json():
                kind, payload = job["kind"], job["payload"]
                label = payload.get("subject") or kind
                try:
                    handler = getattr(ol, kind)
                    result = handler(payload)
                    s.post(f"{url}/api/connector/jobs/{job['id']}/complete", json={"ok": True, "result": result}, timeout=30)
                    log.info("Done   %-20s %s", kind, label)
                except Exception as e:
                    msg = str(e)
                    if hasattr(e, "excepinfo") and e.excepinfo and len(e.excepinfo) > 2 and e.excepinfo[2]:
                        msg = e.excepinfo[2]
                    log.warning("Failed %-20s %s: %s", kind, label, msg)
                    s.post(f"{url}/api/connector/jobs/{job['id']}/complete", json={"ok": False, "error": msg[:1500]}, timeout=30)
            backoff = poll
            time.sleep(poll)
        except KeyboardInterrupt:
            log.info("Stopped.")
            return
        except requests.RequestException as e:
            log.warning("Can't reach HireModus (%s). Retrying in %ss.", e.__class__.__name__, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
        except Exception:
            log.error("Unexpected error:\n%s", traceback.format_exc())
            time.sleep(15)
            try:
                ol = Outlook()  # Outlook may have been restarted
            except Exception:
                pass


if __name__ == "__main__":
    main()
