import os
import secrets
import string
from datetime import datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .db import get_db
from . import models

SECRET_KEY = os.environ.get("HIREMODUS_SECRET_KEY") or "dev-only-change-me-" + "x" * 24
ALGO = "HS256"
STAFF_TOKEN_HOURS = int(os.environ.get("HIREMODUS_TOKEN_HOURS", "12"))

bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def random_password(n: int = 10) -> str:
    # no look-alike characters, since candidates type these from an email
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def random_code(n: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(n))


def make_token(sub: str, scope: str, hours: float, extra: dict | None = None) -> str:
    payload = {"sub": sub, "scope": scope, "exp": datetime.utcnow() + timedelta(hours=hours)}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGO)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGO])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid. Please sign in again.")


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> models.User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    data = decode_token(creds.credentials)
    if data.get("scope") != "staff":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    user = db.get(models.User, int(data["sub"]))
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    return user


def require_roles(*roles: str):
    def dep(user: models.User = Depends(current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role can't do this")
        return user
    return dep


staff = require_roles("admin", "recruiter", "interviewer")
recruiter = require_roles("admin", "recruiter")
admin = require_roles("admin")


def candidate_session(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> tuple[models.TestAssignment, str]:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    data = decode_token(creds.credentials)
    if data.get("scope") not in ("cand-login", "cand-test"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    a = db.get(models.TestAssignment, int(data["sub"]))
    if not a or a.status == "revoked":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This test login is no longer active")
    # a token issued before a later unlock/login is still fine; status checks happen per endpoint
    return a, data["scope"]


def connector_user(
    x_connector_key: str | None = Header(default=None), db: Session = Depends(get_db)
) -> models.User:
    if not x_connector_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing connector key")
    user = db.query(models.User).filter(models.User.connector_key == x_connector_key).first()
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown connector key")
    return user
