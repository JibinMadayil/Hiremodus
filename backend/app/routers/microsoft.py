"""Settings > Microsoft 365, Microsoft sign-in, and each person's choice of Graph or the Outlook connector."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, msgraph
from ..perms import require, has
from ..security import current_user, make_token, STAFF_TOKEN_HOURS
from ..services import get_setting, audit

router = APIRouter(tags=["microsoft"])


def _public(db, request: Request) -> dict:
    c = msgraph.config(db)
    return {
        "ms_tenant_id": c["tenant"], "ms_client_id": c["client_id"], "ms_public_url": c["public_url"],
        "secret_set": bool(c["secret"]), "configured": msgraph.configured(db),
        "ms_signin_enabled": get_setting(db, "ms_signin_enabled"), "ms_password_signin": get_setting(db, "ms_password_signin"),
        "ms_graph_enabled": get_setting(db, "ms_graph_enabled"), "ms_default_transport": get_setting(db, "ms_default_transport"),
        "redirect_uri": msgraph.redirect_uri(db, str(request.base_url)),
        "redirect_is_https": msgraph.redirect_uri(db, str(request.base_url)).startswith(("https://", "http://localhost", "http://127.0.0.1")),
        "users": [{"id": u.id, "name": u.name, "email": u.email, "mail_transport": u.mail_transport or "default",
                   "uses": msgraph.transport_for(db, u), "signed_in_with_microsoft": bool(u.entra_oid)}
                  for u in db.query(models.User).filter(models.User.active.is_(True)).order_by(models.User.name)],
    }


@router.get("/api/microsoft/settings")
def get_ms(request: Request, user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    return _public(db, request)


@router.put("/api/microsoft/settings")
def put_ms(body: dict, request: Request, user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    if body.get("ms_password_signin", "everyone") not in ("everyone", "admins"):
        raise HTTPException(400, "Password sign-in must be 'everyone' or 'admins'")
    if body.get("ms_default_transport", "connector") not in ("connector", "graph"):
        raise HTTPException(400, "Default must be 'connector' or 'graph'")
    url = str(body.get("ms_public_url", "")).strip()
    if url and not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise HTTPException(400, "Microsoft only accepts an https:// address here (or http://localhost)")
    before = {k: get_setting(db, k) for k in ("ms_signin_enabled", "ms_graph_enabled", "ms_tenant_id", "ms_client_id")}
    msgraph.save_settings(db, body)
    turning_on = body.get("ms_signin_enabled") == "true" or body.get("ms_graph_enabled") == "true"
    if turning_on and not msgraph.configured(db):
        db.rollback()
        raise HTTPException(400, "Fill in the tenant ID, client ID and client secret before switching anything on")
    changes = [k for k, v in before.items() if get_setting(db, k) != v]
    if body.get("ms_client_secret"):
        changes.append("client secret replaced")
    if changes:
        audit(db, user, "microsoft_settings_changed", ", ".join(changes))
    db.commit()
    return _public(db, request)


class TestIn(BaseModel):
    mailbox: str = ""


@router.post("/api/microsoft/test")
def test(body: TestIn, user=Depends(require("settings.manage")), db: Session = Depends(get_db)):
    if not msgraph.configured(db):
        raise HTTPException(400, "Save the tenant ID, client ID and client secret first")
    return {"steps": msgraph.test_connection(db, (body.mailbox or user.email).strip().lower())}


class TransportIn(BaseModel):
    mail_transport: str  # default | connector | graph


@router.put("/api/me/mail-transport")
def my_transport(body: TransportIn, user=Depends(current_user), db: Session = Depends(get_db)):
    return _set_transport(db, user, user, body.mail_transport)


@router.put("/api/users/{uid}/mail-transport")
def user_transport(uid: int, body: TransportIn, user=Depends(require("users.manage")), db: Session = Depends(get_db)):
    target = db.get(models.User, uid)
    if not target:
        raise HTTPException(404, "User not found")
    return _set_transport(db, user, target, body.mail_transport)


def _set_transport(db, actor, target, value):
    if value not in ("default", "connector", "graph"):
        raise HTTPException(400, "Choose default, connector or graph")
    if value == "graph" and not msgraph.graph_on(db):
        raise HTTPException(400, "Microsoft 365 email isn't switched on yet (Settings > Microsoft 365)")
    target.mail_transport = value
    audit(db, actor, "mail_route_changed", f"{target.name}: {value}")
    db.commit()
    return {"mail_transport": value, "uses": msgraph.transport_for(db, target)}


# ---------------------------------------------------------------- sign-in

@router.get("/api/auth/options")
def auth_options(db: Session = Depends(get_db)):
    on = msgraph.signin_on(db)
    return {"microsoft": on, "password": get_setting(db, "ms_password_signin") if on else "everyone"}


@router.get("/api/auth/microsoft/start")
def ms_start(request: Request, db: Session = Depends(get_db)):
    if not msgraph.signin_on(db):
        return RedirectResponse("/#ms_error=" + quote("Microsoft sign-in isn't switched on"))
    try:
        return RedirectResponse(msgraph.start_signin(db, str(request.base_url)))
    except Exception as e:
        return RedirectResponse("/#ms_error=" + quote(str(e)[:300]))


@router.get("/api/auth/microsoft/callback")
def ms_callback(request: Request, db: Session = Depends(get_db)):
    try:
        who = msgraph.finish_signin(db, dict(request.query_params))
    except Exception as e:
        return RedirectResponse("/#ms_error=" + quote(str(e)[:300]))
    u = None
    if who["oid"]:
        u = db.query(models.User).filter(models.User.entra_oid == who["oid"]).first()
    if not u and who["email"]:
        u = db.query(models.User).filter(models.User.email == who["email"]).first()
        if u and u.entra_oid and u.entra_oid != who["oid"]:
            u = None  # that HireModus user is already linked to a different Microsoft account
    if not u or not u.active:
        audit(db, None, "microsoft_sign_in_refused", f"{who['email'] or who['oid']}: not a HireModus user" if not u else f"{u.email}: account switched off")
        db.commit()
        return RedirectResponse("/#ms_error=" + quote(
            f"{who['email'] or 'This account'} isn't set up in HireModus. Ask an admin to add you in Settings > Users."))
    if not u.entra_oid:
        u.entra_oid = who["oid"]
    u.must_change_password = False  # they signed in with Microsoft; the temporary HireModus password doesn't matter
    audit(db, u, "sign_in", "with Microsoft")
    db.commit()
    return RedirectResponse("/#ms_token=" + make_token(str(u.id), "staff", STAFF_TOKEN_HOURS))


def password_allowed(db, u: models.User) -> bool:
    if not msgraph.signin_on(db) or get_setting(db, "ms_password_signin") != "admins":
        return True
    return has(u, "users.manage")
