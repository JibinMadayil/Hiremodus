"""Microsoft 365: Entra ID sign-in and Microsoft Graph for email, meeting invites, free/busy and candidate replies.

Off until an admin fills in Settings > Microsoft 365. Each person's email goes through Graph or their Outlook connector
(transport_for). Graph calls use the app's own permission (client credentials), limited by IT to recruiters' mailboxes."""
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import models
from .services import get_setting, set_setting, split_emails

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = ["https://graph.microsoft.com/.default"]
SIGNIN_SCOPES = ["User.Read"]
TIMEOUT = 30


class GraphError(Exception):
    pass


# ---------------------------------------------------------------- configuration

def config(db: Session) -> dict:
    return {
        "tenant": get_setting(db, "ms_tenant_id").strip(),
        "client_id": get_setting(db, "ms_client_id").strip(),
        "secret": get_setting(db, "ms_client_secret").strip(),
        "public_url": get_setting(db, "ms_public_url").strip().rstrip("/"),
    }


def configured(db: Session) -> bool:
    c = config(db)
    return bool(c["tenant"] and c["client_id"] and c["secret"])


def graph_on(db: Session) -> bool:
    return configured(db) and get_setting(db, "ms_graph_enabled") == "true"


def signin_on(db: Session) -> bool:
    return configured(db) and get_setting(db, "ms_signin_enabled") == "true"


def transport_for(db: Session, user: models.User) -> str:
    """'graph' or 'connector' for this person's email, invites and reply checks."""
    if not graph_on(db):
        return "connector"
    choice = user.mail_transport or "default"
    if choice in ("graph", "connector"):
        return choice
    return "graph" if get_setting(db, "ms_default_transport") == "graph" else "connector"


# ---------------------------------------------------------------- HTTP and tokens (tests replace _request and _token)

_apps: dict = {}


def _msal_app(cfg: dict):
    import msal
    key = (cfg["tenant"], cfg["client_id"], cfg["secret"])
    if key not in _apps:
        _apps.clear()
        _apps[key] = msal.ConfidentialClientApplication(
            cfg["client_id"], authority=f"https://login.microsoftonline.com/{cfg['tenant']}", client_credential=cfg["secret"])
    return _apps[key]


def _token(cfg: dict) -> str:
    r = _msal_app(cfg).acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in r:
        raise GraphError(r.get("error_description") or r.get("error") or "Microsoft didn't return a token")
    return r["access_token"]


def _request(method: str, url: str, token: str, json=None, headers=None):
    import requests
    h = {"Authorization": "Bearer " + token}
    h.update(headers or {})
    for attempt in range(3):
        r = requests.request(method, url, json=json, headers=h, timeout=TIMEOUT)
        if r.status_code in (429, 503, 504) and attempt < 2:
            time.sleep(min(int(r.headers.get("Retry-After", "2") or 2), 20))
            continue
        break
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
            msg = f"{err.get('code', r.status_code)}: {err.get('message', '')}"
        except Exception:
            msg = f"HTTP {r.status_code}"
        raise GraphError(_explain(msg))
    if r.status_code == 204 or not r.content:
        return {}
    return r.json()


def _explain(msg: str) -> str:
    if "ErrorAccessDenied" in msg or "Access is denied" in msg or "AccessDenied" in msg:
        return msg + " (IT hasn't allowed HireModus to use this mailbox yet, or admin consent is missing.)"
    if "MailboxNotEnabledForRESTAPI" in msg or "ResourceNotFound" in msg:
        return msg + " (This person's mailbox wasn't found in Microsoft 365.)"
    return msg


class Client:
    def __init__(self, db: Session):
        self.cfg = config(db)
        self._tok = None

    def call(self, method: str, path: str, json=None, headers=None):
        if self._tok is None:
            self._tok = _token(self.cfg)
        url = path if path.startswith("http") else GRAPH + path
        return _request(method, url, self._tok, json=json, headers=headers)


# ---------------------------------------------------------------- outbox jobs

def _people(text: str) -> list[dict]:
    return [{"emailAddress": {"address": e}} for e in split_emails(text or "")]


def _utc(local_iso: str) -> str:
    from .aging import to_utc
    return to_utc(datetime.fromisoformat(local_iso).replace(tzinfo=None)).isoformat(timespec="seconds")


def run_job(db: Session, job: models.OutboxJob, owner: models.User) -> dict:
    g = Client(db)
    p = job.payload or {}
    me = owner.email
    if job.kind == "send_mail":
        g.call("POST", f"/users/{me}/sendMail", {"message": {
            "subject": p.get("subject", ""), "body": {"contentType": "Text", "content": p.get("body", "")},
            "toRecipients": _people(p.get("to")), "ccRecipients": _people(p.get("cc"))}, "saveToSentItems": True})
        return {"via": "graph"}
    if job.kind == "reply_mail":
        gid = p.get("graph_id")
        if gid:
            try:
                g.call("POST", f"/users/{me}/messages/{gid}/reply", {
                    "message": {"ccRecipients": _people(p.get("cc"))}, "comment": p.get("body", "")})
                return {"via": "graph", "threaded": True}
            except GraphError:
                pass  # the message may have been deleted from the inbox: send it as a new email instead
        g.call("POST", f"/users/{me}/sendMail", {"message": {
            "subject": p.get("subject", ""), "body": {"contentType": "Text", "content": p.get("body", "") + p.get("quoted", "")},
            "toRecipients": _people(p.get("to")), "ccRecipients": _people(p.get("cc"))}, "saveToSentItems": True})
        return {"via": "graph", "threaded": False}
    if job.kind == "create_appointment":
        ev = g.call("POST", f"/users/{me}/events", {
            "subject": p["subject"], "body": {"contentType": "Text", "content": p.get("body", "")},
            "start": {"dateTime": _utc(p["start"]), "timeZone": "UTC"}, "end": {"dateTime": _utc(p["end"]), "timeZone": "UTC"},
            "location": {"displayName": p.get("location", "")},
            "attendees": [{"emailAddress": {"address": e}, "type": "required"} for e in split_emails(p.get("required"))]
                         + [{"emailAddress": {"address": e}, "type": "optional"} for e in split_emails(p.get("optional"))]})
        return {"entry_id": "graph:" + ev["id"], "via": "graph"}
    if job.kind == "update_appointment":
        eid = _graph_event_id(p.get("entry_id", ""))
        g.call("PATCH", f"/users/{me}/events/{eid}", {
            "start": {"dateTime": _utc(p["start"]), "timeZone": "UTC"}, "end": {"dateTime": _utc(p["end"]), "timeZone": "UTC"}})
        return {"entry_id": p["entry_id"], "via": "graph"}
    if job.kind == "cancel_appointment":
        eid = _graph_event_id(p.get("entry_id", ""))
        g.call("POST", f"/users/{me}/events/{eid}/cancel", {"comment": p.get("body", "")[:1000]})
        return {"via": "graph"}
    if job.kind == "free_busy":
        start_local = datetime.fromisoformat(p["start_date"]).replace(hour=0, minute=0, second=0, microsecond=0)
        days = int(p["days"])
        emails = [me if e == "__me__" else e for e in p["emails"]]
        from .aging import to_utc
        start_utc = to_utc(start_local)
        r = g.call("POST", f"/users/{me}/calendar/getSchedule", {
            "schedules": emails, "availabilityViewInterval": 30,
            "startTime": {"dateTime": start_utc.isoformat(timespec="seconds"), "timeZone": "UTC"},
            "endTime": {"dateTime": (start_utc + timedelta(days=days)).isoformat(timespec="seconds"), "timeZone": "UTC"}})
        found = {s.get("scheduleId", "").lower(): s for s in r.get("value", [])}
        out = {}
        for key, addr in zip(p["emails"], emails):
            s = found.get(addr.lower())
            entry = {"start_date": start_local.date().isoformat(), "fb": "", "resolved": False}
            if s and "error" not in s:
                entry.update(fb=(s.get("availabilityView") or "")[: days * 48], resolved=True)
            elif s:
                entry["error"] = (s["error"].get("message") or "")[:200]
            out[key] = entry
        return {"free_busy": out, "me": me}
    raise GraphError(f"Unknown job type {job.kind}")


def _graph_event_id(entry_id: str) -> str:
    if not entry_id.startswith("graph:"):
        raise GraphError("This meeting was booked through the Outlook connector, so it has to be changed from that person's Outlook. "
                         "Switch them back to the connector, or cancel and book it again.")
    return entry_id[6:]


# ---------------------------------------------------------------- replies

def fetch_replies(db: Session, owner: models.User, since: datetime, addresses: set[str]) -> list[dict]:
    """Messages in owner's Inbox since `since` from any of `addresses`, in the same shape the connector sends."""
    from .mailbox import MAX_ATTACHMENT
    g = Client(db)
    sel = "id,internetMessageId,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments"
    url = (f"/users/{owner.email}/mailFolders/inbox/messages?$select={sel}&$top=50&$orderby=receivedDateTime desc"
           f"&$filter=receivedDateTime ge {since.replace(microsecond=0).isoformat()}Z")
    out = []
    for _ in range(40):  # up to 2000 messages per check
        page = g.call("GET", url, headers={"Prefer": 'outlook.body-content-type="text"'})
        for m in page.get("value", []):
            sender = ((m.get("from") or {}).get("emailAddress") or {})
            addr = (sender.get("address") or "").lower()
            if addr not in addresses:
                continue
            msg = {"graph_id": m["id"], "message_id": m.get("internetMessageId", ""), "from": addr, "from_name": sender.get("name", ""),
                   "to": "; ".join(r["emailAddress"]["address"] for r in m.get("toRecipients", []) if r.get("emailAddress")),
                   "cc": "; ".join(r["emailAddress"]["address"] for r in m.get("ccRecipients", []) if r.get("emailAddress")),
                   "subject": m.get("subject", ""), "received_at": m.get("receivedDateTime"),
                   "body": (m.get("body") or {}).get("content", ""), "attachments": []}
            if m.get("hasAttachments"):
                atts = g.call("GET", f"/users/{owner.email}/messages/{m['id']}/attachments")
                for a in atts.get("value", []):
                    if a.get("@odata.type") == "#microsoft.graph.fileAttachment" and (a.get("size") or 0) <= MAX_ATTACHMENT and not a.get("isInline"):
                        msg["attachments"].append({"name": a.get("name"), "size": a.get("size"), "content_b64": a.get("contentBytes", "")})
            out.append(msg)
        url = page.get("@odata.nextLink")
        if not url:
            break
    return out


# ---------------------------------------------------------------- sign-in

_flows: dict = {}  # state -> (flow, created)


def redirect_uri(db: Session, base_url: str) -> str:
    base = config(db)["public_url"] or base_url.rstrip("/")
    return base + "/api/auth/microsoft/callback"


def start_signin(db: Session, base_url: str) -> str:
    cfg = config(db)
    flow = _msal_app(cfg).initiate_auth_code_flow(SIGNIN_SCOPES, redirect_uri=redirect_uri(db, base_url), prompt="select_account")
    now = time.time()
    for k in [k for k, (_, t) in _flows.items() if now - t > 900]:
        _flows.pop(k, None)
    _flows[flow["state"]] = (flow, now)
    return flow["auth_uri"]


def finish_signin(db: Session, params: dict) -> dict:
    """Returns the signed-in person's claims: oid, tid, email."""
    state = params.get("state", "")
    flow = _flows.pop(state, (None, 0))[0]
    if not flow:
        raise GraphError("The sign-in took too long or was started in another window. Please try again.")
    if params.get("error"):
        raise GraphError(params.get("error_description") or params["error"])
    r = _msal_app(config(db)).acquire_token_by_auth_code_flow(flow, params)
    if "id_token_claims" not in r:
        raise GraphError(r.get("error_description") or "Microsoft didn't confirm who you are")
    cl = r["id_token_claims"]
    if (cl.get("tid") or "").lower() != config(db)["tenant"].lower():
        raise GraphError("That Microsoft account belongs to a different organisation.")
    return {"oid": cl.get("oid", ""), "tid": cl.get("tid", ""),
            "email": (cl.get("email") or cl.get("preferred_username") or "").strip().lower(), "name": cl.get("name", "")}


def test_connection(db: Session, mailbox: str) -> list[dict]:
    """Checks the settings step by step for the Settings page."""
    steps = []
    try:
        _token(config(db))
        steps.append({"ok": True, "step": "Signed in to Microsoft 365 with the app details"})
    except Exception as e:  # wrong tenant, client ID or secret, or no internet access
        return [{"ok": False, "step": "Signing in to Microsoft 365 with the app details", "error": str(e)[:400]}]
    for label, method, path, body in (
        ("Reading the inbox (for candidate replies)", "GET", f"/users/{mailbox}/mailFolders/inbox/messages?$top=1&$select=id", None),
        ("Reading the calendar (for invites and free/busy)", "GET", f"/users/{mailbox}/calendar?$select=id", None),
    ):
        try:
            Client(db).call(method, path, body)
            steps.append({"ok": True, "step": label})
        except GraphError as e:
            steps.append({"ok": False, "step": label, "error": str(e)})
    return steps


def save_settings(db: Session, body: dict):
    for k in ("ms_tenant_id", "ms_client_id", "ms_public_url", "ms_signin_enabled", "ms_password_signin",
              "ms_graph_enabled", "ms_default_transport"):
        if k in body:
            set_setting(db, k, str(body[k]).strip())
    if body.get("ms_client_secret"):
        set_setting(db, "ms_client_secret", str(body["ms_client_secret"]).strip())
    if body.get("clear_secret"):
        set_setting(db, "ms_client_secret", "")
    _apps.clear()
