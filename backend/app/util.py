from datetime import datetime, date

from fastapi import HTTPException
from sqlalchemy import inspect


def row(obj, exclude: set[str] = frozenset()) -> dict:
    if obj is None:
        return None
    out = {}
    for c in inspect(obj).mapper.column_attrs:
        if c.key in exclude:
            continue
        v = getattr(obj, c.key)
        if isinstance(v, (datetime, date)):
            v = v.isoformat()
        out[c.key] = v
    return out


def rows(objs, exclude: set[str] = frozenset()) -> list[dict]:
    return [row(o, exclude) for o in objs]


def get_or_404(db, model, id_, what="Record"):
    obj = db.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{what} not found")
    return obj


def apply(obj, data: dict, allowed: set[str] | None = None):
    mapper = inspect(obj).mapper
    cols = {c.key for c in mapper.column_attrs} - {"id"}
    for k, v in data.items():
        if k in cols and (allowed is None or k in allowed):
            try:
                col_type = mapper.columns[k].type.python_type
            except (NotImplementedError, AttributeError):
                col_type = None
            if v is not None and col_type is date and isinstance(v, str):
                v = date.fromisoformat(v[:10])
            elif v is not None and col_type is datetime and isinstance(v, str):
                v = datetime.fromisoformat(v)
            setattr(obj, k, v)
    return obj
