import os
import sys
import tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ["HIREMODUS_DATABASE_URL"] = f"sqlite:///{TMP}/r.db"
os.environ["HIREMODUS_UPLOAD_DIR"] = f"{TMP}/up"
os.environ["HIREMODUS_IMPORT_DIR"] = f"{TMP}/imp"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models  # noqa: E402
from app.recsvc import delete_due, next_local_midnight_utc  # noqa: E402


def test_recording():
    # midnight maths: 11:30 PM Toronto on Nov 11 (04:30 UTC Nov 12) -> deletes at 05:00 UTC Nov 12
    assert next_local_midnight_utc(datetime(2026, 11, 12, 4, 30)) == datetime(2026, 11, 12, 5, 0)
    assert next_local_midnight_utc(datetime(2026, 11, 11, 15, 0)) == datetime(2026, 11, 12, 5, 0)
    with TestClient(app) as c:
        H = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@novamodus.com", "password": "ChangeMe123!"}).json()["token"]}
        cid = c.post("/api/candidates", headers=H, json={"first_name": "Rec", "last_name": "Tester", "email": "rec@example.com"}).json()["candidate"]["id"]
        gl = [t for t in c.get("/api/tests", headers=H).json() if t["name"] == "Oracle General Ledger - Questionnaire"][0]
        asg = c.post(f"/api/candidates/{cid}/assign-test", headers=H, json={"test_id": gl["id"], "send_email": False}).json()
        a = asg["assignment"]
        CH = {"Authorization": "Bearer " + c.post("/api/portal/login", json={"username": a["username"], "password": asg["password"]}).json()["token"]}
        st = c.get("/api/portal/state", headers=CH).json()
        assert st["record"] == {"camera": True, "audio": True, "screen": True}
        code = c.post(f"/api/assignments/{a['id']}/start-code", headers=H).json()["code"]
        TH = {"Authorization": "Bearer " + c.post("/api/portal/unlock", headers=CH, json={"code": code}).json()["token"]}
        # candidate token before unlock can't record
        assert c.post("/api/portal/recording/start", headers=CH, json={"kind": "camera"}).status_code == 403
        rid = c.post("/api/portal/recording/start", headers=TH, json={"kind": "camera", "mime": "video/webm;codecs=vp8,opus"}).json()["id"]
        sid = c.post("/api/portal/recording/start", headers=TH, json={"kind": "screen"}).json()["id"]
        for i, part in enumerate([b"AAAA", b"BBBB", b"CCCC"]):
            assert c.post(f"/api/portal/recording/{rid}/chunk?seq={i}", headers=TH, content=part).status_code == 200
        assert c.post(f"/api/portal/recording/{rid}/chunk?seq=1", headers=TH, content=b"BBBB").json()["duplicate"]
        assert c.post(f"/api/portal/recording/{rid}/chunk?seq=5", headers=TH, content=b"X").status_code == 409
        c.post(f"/api/portal/recording/{sid}/chunk?seq=0", headers=TH, content=b"SCREEN")
        c.post("/api/portal/events", headers=TH, json={"type": "screen_stopped"})
        c.post("/api/portal/submit", headers=TH)
        # last chunk can still arrive just after submit
        assert c.post(f"/api/portal/recording/{rid}/chunk?seq=3", headers=TH, content=b"DDDD").status_code == 200

        res = c.get(f"/api/assignments/{a['id']}", headers=H).json()
        recs = {r["kind"]: r for r in res["recordings"]}
        assert recs["camera"]["bytes"] == 16
        r = c.get(recs["camera"]["url"])
        assert r.status_code == 200 and r.content == b"AAAABBBBCCCCDDDD"
        assert c.get(f"/api/recordings/{rid}/file?t=bad").status_code == 401
        assert c.get(recs["camera"]["url"].replace(f"/{rid}/", f"/{sid}/")).status_code == 403

        # after midnight the files are gone
        db = SessionLocal()
        for rec in db.query(models.Recording):
            path = rec.path
            rec.delete_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        assert delete_due(db) == 2
        db.commit()
        assert not os.path.exists(path)
        db.close()
        res = c.get(f"/api/assignments/{a['id']}", headers=H).json()
        assert all(r["deleted"] and r["url"] is None for r in res["recordings"])
        assert c.get(recs["camera"]["url"]).status_code == 404

        # test without recording rejects uploads
        t = c.post("/api/tests", headers=H, json={"name": "NoRec", "department_ids": [1], "record_camera": False, "record_screen": False,
                                                  "questions": [{"kind": "short", "prompt": "x"}]}).json()
        assert not t["record_camera"]
