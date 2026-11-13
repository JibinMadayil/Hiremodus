import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..security import (verify_password, hash_password, make_token, current_user, STAFF_TOKEN_HOURS)
from ..services import audit
from ..perms import associate_only, has, user_perms, dept_scope

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


def user_out(u: models.User) -> dict:
    online = bool(u.connector_last_seen and u.connector_last_seen > datetime.utcnow() - timedelta(seconds=90))
    return {
        "id": u.id, "name": u.name, "email": u.email, "active": u.active,
        "role_ids": [r.id for r in u.roles], "roles": [r.name for r in u.roles],
        "permissions": sorted(user_perms(u)), "department_scoped": dept_scope(u) is not None,
        "scope_ids": dept_scope(u),  # null = every department; a list = only these (assigned + CC lists)
        "associate": associate_only(u),
        "must_change_password": u.must_change_password,
        "department_ids": [d.id for d in u.departments],
        "connector_online": online,
        "connector_last_seen": u.connector_last_seen.isoformat() + "Z" if u.connector_last_seen else None,
        "connector_info": u.connector_info or {},
        "has_connector_key": bool(u.connector_key),
        "mail_transport": u.mail_transport or "default",
        "signed_in_with_microsoft": bool(u.entra_oid),
    }


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.query(models.User).filter(models.User.email == body.email.strip().lower()).first()
    if not u or not u.active or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Email or password is incorrect")
    from .microsoft import password_allowed
    if not password_allowed(db, u):
        raise HTTPException(403, "Use Sign in with Microsoft. Password sign-in is only for admins now.")
    audit(db, u, "sign_in")
    db.commit()
    return {"token": make_token(str(u.id), "staff", STAFF_TOKEN_HOURS), "user": user_out(u)}


@router.get("/me")
def me(user: models.User = Depends(current_user)):
    return user_out(user)


class PwIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: PwIn, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(400, "Use at least 8 characters")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    return {"ok": True}


@router.post("/connector-key")
def new_connector_key(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    if not has(user, "emails.send"):
        raise HTTPException(403, "Your role doesn't send email from HireModus")
    user.connector_key = "hmc_" + secrets.token_urlsafe(32)
    db.commit()
    return {"connector_key": user.connector_key}
