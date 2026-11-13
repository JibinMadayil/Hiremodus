"""Permissions. Users hold one or more roles; a role is a list of these permissions, editable in Settings > Roles."""
from fastapi import Depends, HTTPException

from . import models

PERMISSIONS = {
    "candidates.view": "See candidates",
    "candidates.edit": "Add and edit candidates, move them between stages",
    "candidates.hire": "Move candidates to Hired",
    "candidates.delete": "Delete candidates",
    "candidates.edit_date_added": "Change a candidate's Date added",
    "emails.send": "Send emails from HireModus",
    "interviews.schedule": "Schedule, reschedule and cancel interviews",
    "import.run": "Import from Excel",
    "tests.papers": "See and edit test papers: questions, answer keys, candidate answers, grading",
    "tests.assign": "Assign tests and resend test logins",
    "tests.start_code": "Give start codes",
    "tests.results": "See test scores, integrity logs and recordings",
    "outbox.view_all": "See everyone's Outbox",
    "settings.manage": "Change settings, templates, stages and interview types",
    "users.manage": "Add users and change their roles",
    "audit.view": "See the audit log",
}

ALL = list(PERMISSIONS)
HIRING = ["candidates.view", "candidates.edit", "candidates.hire", "emails.send", "interviews.schedule", "import.run",
          "tests.papers", "tests.assign", "tests.start_code", "tests.results"]
ASSOCIATE = ["candidates.view", "candidates.edit", "emails.send"]

BUILTIN_ROLES = [
    dict(key="admin", name="Admin", builtin=True,
         permissions=[p for p in ALL if p != "tests.papers"],
         description="Every department, settings and users, but not question papers. Combine with Recruiter for everything."),
    dict(key="recruiter", name="Recruiter", builtin=True, permissions=HIRING, department_scoped=True,
         description="Works on their own departments' candidates and test papers, plus the AI and Screening stages."),
    dict(key="associate", name="Associate", builtin=True, permissions=ASSOCIATE, department_scoped=True,
         description="Adds candidates and works the AI and Screening stages. Sees where everyone else is, read-only."),
]


def user_perms(user: models.User) -> set[str]:
    out: set[str] = set()
    for r in user.roles or []:
        out.update(r.permissions or [])
    return out


def dept_scope(user: models.User) -> list[int] | None:
    """None means the user sees every department. Otherwise: the departments ticked on their account, plus every
    department whose CC list includes their email."""
    roles = user.roles or []
    if not roles or any(not r.department_scoped for r in roles):
        return None
    if all(r.key == "associate" for r in roles):
        return []  # associates work only on candidates that don't have a department yet
    ids = {d.id for d in user.departments}
    if True:
        from sqlalchemy.orm import object_session
        from .services import split_emails
        db = object_session(user)
        if db is not None:
            for d in db.query(models.Department):
                if user.email.lower() in split_emails(d.cc_emails):
                    ids.add(d.id)
    return sorted(ids)


def has(user: models.User, perm: str) -> bool:
    return perm in user_perms(user)


def require(*perms: str):
    from .security import current_user

    def dep(user: models.User = Depends(current_user)) -> models.User:
        mine = user_perms(user)
        missing = [p for p in perms if p not in mine]
        if missing:
            raise HTTPException(403, "Your role doesn't allow this (" + ", ".join(PERMISSIONS.get(p, p) for p in missing) + ")")
        return user
    return dep


def require_any(*perms: str):
    from .security import current_user

    def dep(user: models.User = Depends(current_user)) -> models.User:
        if not (user_perms(user) & set(perms)):
            raise HTTPException(403, "Your role doesn't allow this")
        return user
    return dep


# ---------------------------------------------------------------- candidate access

def pending_transfer_ids(db, scope: list[int]) -> set[int]:
    if not scope:
        return set()
    return {cid for (cid,) in db.query(models.Transfer.candidate_id).filter(
        models.Transfer.status == "pending", models.Transfer.to_department_id.in_(scope))}


def full_access_filter(db, user):
    """SQL condition for candidates this user can fully open. None = no restriction."""
    from sqlalchemy import or_
    scope = dept_scope(user)
    if scope is None:
        return None
    conds = [models.Candidate.department_id.is_(None)]
    if scope:
        conds.append(models.Candidate.department_id.in_(scope))
    extra = pending_transfer_ids(db, scope)
    if extra:
        conds.append(models.Candidate.id.in_(extra))
    return or_(*conds)


def limit_full(query, db, user):
    cond = full_access_filter(db, user)
    return query if cond is None else query.filter(cond)


_UNSET = object()


def candidate_access(db, user, c: models.Candidate, scope=_UNSET, pending=None) -> str:
    if scope is _UNSET:
        scope = dept_scope(user)
    if scope is None or c.department_id is None or c.department_id in scope:
        return "full"
    if pending is None:
        pending = pending_transfer_ids(db, scope)
    return "full" if c.id in pending else "summary"


def associate_only(user) -> bool:
    roles = [r for r in user.roles]
    return bool(roles) and all(r.key == "associate" for r in roles)
