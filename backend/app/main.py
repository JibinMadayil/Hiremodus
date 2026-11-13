import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .db import Base, engine, SessionLocal, add_missing_columns
from . import models
from .seed import seed
from .seed_extras import seed_extras, seed_v2, seed_v3, seed_v4
from .testsvc import expire_if_due
from .recsvc import delete_due
from .aging import due_now as aging_due_now, run as aging_run
from .retention import due_now as retention_due, run as retention_run
from .graphworker import run_once as graph_run_once
from .routers import auth, candidates, interviews, tests, portal, connector, admin, importer, replies, microsoft, feedback

STATIC_DIR = os.environ.get("HIREMODUS_STATIC_DIR",
                            os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))


async def expire_loop():
    """Auto-submit tests whose timer ran out even if the candidate's browser is closed,
    and delete recordings once midnight passes on the day of the test (also on the first run after a restart)."""
    while True:
        db = SessionLocal()
        try:
            changed = False
            for a in db.query(models.TestAssignment).filter_by(status="in_progress"):
                changed |= expire_if_due(db, a)
            changed |= bool(delete_due(db))
            if changed:
                db.commit()
            if aging_due_now(db):
                aging_run(db)
            if retention_due(db):
                retention_run(db)
        except Exception:
            db.rollback()
        finally:
            db.close()
        await asyncio.sleep(30)


def _graph_tick():
    db = SessionLocal()
    try:
        graph_run_once(db)
    except Exception:
        db.rollback()
    finally:
        db.close()


async def graph_loop():
    """Microsoft 365 mail: sends queued jobs for people on Graph and checks their inboxes for candidate replies."""
    while True:
        await asyncio.to_thread(_graph_tick)
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    add_missing_columns()
    db = SessionLocal()
    try:
        seed(db)
        seed_extras(db)  # questionnaires, team logins, demo candidate: added once, also on older databases
        seed_v2(db)  # roles, aging rules, team roles
        seed_v3(db)  # department-only recruiters, associates, test departments
        seed_v4(db)  # interview feedback questions
    finally:
        db.close()
    tasks = [asyncio.create_task(expire_loop()), asyncio.create_task(graph_loop())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="HireModus", version="1.0.0", lifespan=lifespan)

for r in (auth, candidates, interviews, tests, portal, connector, admin, importer, replies, microsoft, feedback):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        f = os.path.join(STATIC_DIR, path)
        if path and os.path.isfile(f) and os.path.abspath(f).startswith(os.path.abspath(STATIC_DIR)):
            return FileResponse(f)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
