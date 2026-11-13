import os
import sys
import tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ["HIREMODUS_DATABASE_URL"] = f"sqlite:///{TMP}/v2.db"
os.environ["HIREMODUS_UPLOAD_DIR"] = f"{TMP}/up"
os.environ["HIREMODUS_IMPORT_DIR"] = f"{TMP}/imp"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models  # noqa: E402


def login(c, email, pw):
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_v2():
    with TestClient(app) as c:
        A = login(c, "areddy@novamodus.com", "HM-Anitha-3Rw9!")
        meta = c.get("/api/meta", headers=A).json()
        roles = {r["key"]: r["id"] for r in meta["roles"]}
        stages = {s["name"]: s["id"] for s in meta["stages"]}
        depts = {d["name"]: d["id"] for d in meta["departments"]}

        # the old AMS contact is gone everywhere
        assert c.post("/api/auth/login", json={"email": "stomar@novamodus.com", "password": "HM-Sidhant-8Mq2!"}).status_code == 401
        import json
        dump = json.dumps([c.get(f"/api/admin/{k}", headers=A).json() for k in ("departments", "email-templates", "interview-templates")]) + json.dumps(c.get("/api/settings", headers=A).json())
        assert "stomar" not in dump.lower() and "sidhant" not in dump.lower()
        assert "alankrutha@novamodus.com or hpatel@novamodus.com" in dump

        # admin-only user can't see test papers; role change is audited
        r = c.post("/api/users", headers=A, json={"name": "Ada Admin", "email": "ada@novamodus.com", "password": "password1", "role_ids": [roles["admin"]]})
        ada_id = r.json()["id"]
        D = login(c, "ada@novamodus.com", "password1")
        assert c.get("/api/tests", headers=D).status_code == 403
        assert c.get("/api/settings", headers=D).status_code == 200
        assert c.get("/api/tests", headers=A).status_code == 200  # Anitha is Admin + Recruiter
        c.put(f"/api/users/{ada_id}", headers=A, json={"role_ids": [roles["admin"], roles["recruiter"]]})
        assert c.get("/api/tests", headers=D).status_code == 200
        log = c.get("/api/audit?action=user_roles_changed", headers=A).json()
        assert log and "Ada Admin: Admin → Admin, Recruiter" in log[0]["detail"]
        # a recruiter can't manage users or change date added
        R = login(c, "alankrutha@novamodus.com", "HM-Alankrutha-5Tz6!")
        assert c.get("/api/users", headers=R).status_code == 403

        # aging
        def make(first, stage, dept=None, days_ago=0):
            cid = c.post("/api/candidates", headers=A, json={"first_name": first, "last_name": "Test", "email": f"{first.lower()}@example.com",
                                                             "stage_id": stages[stage], "department_id": dept}).json()["candidate"]["id"]
            db = SessionLocal()
            cand = db.get(models.Candidate, cid)
            cand.clock_started_at = datetime.utcnow() - timedelta(days=days_ago)
            cand.last_contact_by = db.query(models.User).filter_by(email="alankrutha@novamodus.com").first().id
            db.commit()
            db.close()
            return cid

        fresh = make("Fresh", "Screening", None, 3)
        alert = make("Alerty", "Department Review", depts["HCM"], 35)
        due = make("Duey", "Department Review", depts["HCM"], 50)
        paused = make("Booked", "Department Review", depts["SCM"], 60)
        kept = make("Kept", "AI Interview Sent", None, 60)
        c.post(f"/api/candidates/{kept}/aging-exempt", headers=A, json={"exempt": True})
        db = SessionLocal()
        start = datetime.now() + timedelta(days=3)
        db.add(models.Interview(candidate_id=paused, start=start, end=start + timedelta(minutes=30), status="scheduled", title="x"))
        db.commit()
        db.close()

        lst = {x["first_name"]: x["aging"] for x in c.get("/api/candidates", headers=A).json() if x["last_name"] == "Test"}
        assert lst["Fresh"]["status"] == "ok" and lst["Fresh"]["days"] == 4
        assert lst["Alerty"]["status"] == "alert"
        assert lst["Duey"]["status"] == "due"
        assert lst["Booked"]["status"] == "paused"
        assert lst["Kept"]["status"] == "exempt"
        k = c.get("/api/aging", headers=A).json()
        assert k["over_total"] >= 2

        # Admin cannot edit date added? Anitha (admin) can; Alankrutha (recruiter) can't
        assert c.patch(f"/api/candidates/{fresh}", headers=R, json={"date_added": "2026-01-01"}).status_code == 403
        assert c.patch(f"/api/candidates/{fresh}", headers=A, json={"date_added": "2026-01-01"}).status_code == 200
        assert c.get("/api/audit?q=date_added", headers=A).status_code == 200

        res = c.post("/api/aging/run", headers=A).json()
        assert [r["name"] for r in res["rejected"]] == ["Duey Test"]
        assert res["alert_emails"] >= 1
        cands = {x["first_name"]: x for x in c.get("/api/candidates", headers=A).json() if x["last_name"] == "Test"}
        assert cands["Duey"]["stage_id"] == stages["Rejected"]
        assert cands["Booked"]["stage_id"] == stages["Department Review"]
        assert cands["Kept"]["stage_id"] == stages["AI Interview Sent"]
        jobs = c.get("/api/jobs", headers=A).json()  # sent from Anitha's Outlook
        hcm = [j for j in jobs if j["description"] == "Aging alert: HCM"]
        assert hcm
        full = c.get(f"/api/jobs/{hcm[0]['id']}", headers=A).json()["payload"]
        assert full["to"] == "areddy@novamodus.com"
        assert "sahuja@novamodus.com" in full["cc"] and "alankrutha@novamodus.com" in full["cc"]
        assert "Alerty Test" in full["body"]
        assert any(j["description"] == "Automatic rejection: Duey Test" for j in jobs)
        notes = c.get("/api/notifications", headers=A).json()
        assert notes["unread"] >= 2

        # contact resets the clock
        c.post(f"/api/candidates/{alert}/contacted", headers=A)
        a2 = c.get(f"/api/candidates/{alert}", headers=A).json()["candidate"]["aging"]
        assert a2["days"] == 1 and a2["status"] == "ok"
        # an email to the candidate also resets it
        et = {t["key"]: t["id"] for t in meta["email_templates"]}
        c.post(f"/api/candidates/{fresh}/email/send", headers=A, json={"template_id": et["ai_invite"]})
        assert c.get(f"/api/candidates/{fresh}", headers=A).json()["candidate"]["aging"]["days"] == 1

        # question pools + shuffled options grade correctly
        body = {"name": "Pool", "department_ids": [1], "duration_min": 10, "shuffle_options": True, "pool_choice": 2, "pool_written": 1, "questions": [
            {"kind": "mcq", "prompt": f"Q{i}", "options": ["right", "w1", "w2", "w3"], "correct_index": 0} for i in range(4)
        ] + [{"kind": "short", "prompt": "W1"}, {"kind": "short", "prompt": "W2"}]}
        t = c.post("/api/tests", headers=A, json=body).json()
        asg = c.post(f"/api/candidates/{fresh}/assign-test", headers=A, json={"test_id": t["id"], "send_email": False}).json()
        CH = {"Authorization": "Bearer " + c.post("/api/portal/login", json={"username": asg["assignment"]["username"], "password": asg["password"]}).json()["token"]}
        code = c.post(f"/api/assignments/{asg['assignment']['id']}/start-code", headers=A).json()["code"]
        TH = {"Authorization": "Bearer " + c.post("/api/portal/unlock", headers=CH, json={"code": code}).json()["token"]}
        paper = c.get("/api/portal/test", headers=TH).json()
        assert len(paper["questions"]) == 3
        for q in paper["questions"]:
            if q["kind"] == "mcq":
                c.put(f"/api/portal/answers/{q['id']}", headers=TH, json={"value": str(q["options"].index("right"))})
        again = c.get("/api/portal/test", headers=TH).json()
        for q in again["questions"]:
            if q["kind"] == "mcq":
                assert q["options"][int(q["value"])] == "right"
        c.post("/api/portal/submit", headers=TH)
        res = c.get(f"/api/assignments/{asg['assignment']['id']}", headers=A).json()
        assert res["auto_score"] == 2 and res["total_points"] == 3 and len(res["items"]) == 3
        # admin without recruiter sees the result but not the paper
        c.put(f"/api/users/{ada_id}", headers=A, json={"role_ids": [roles["admin"]]})
        res2 = c.get(f"/api/assignments/{asg['assignment']['id']}", headers=D).json()
        assert res2["items"] == [] and res2["can_see_papers"] is False and res2["auto_score"] == 2
