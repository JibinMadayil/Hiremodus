import os
import sys
import tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ["HIREMODUS_DATABASE_URL"] = f"sqlite:///{TMP}/t.db"
os.environ["HIREMODUS_UPLOAD_DIR"] = f"{TMP}/up"
os.environ["HIREMODUS_IMPORT_DIR"] = f"{TMP}/imp"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

WORKBOOK = os.environ.get("HM_WORKBOOK")


def test_everything():
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"email": "admin@novamodus.com", "password": "ChangeMe123!"})
        assert r.status_code == 200, r.text
        H = {"Authorization": "Bearer " + r.json()["token"]}
        meta = c.get("/api/meta", headers=H).json()
        stages = {s["name"]: s["id"] for s in meta["stages"]}
        depts = {d["name"]: d["id"] for d in meta["departments"]}
        tpls = {t["name"]: t for t in meta["interview_templates"]}
        etpl = {t["key"]: t["id"] for t in meta["email_templates"]}
        assert len(meta["modules"]) == 19

        # create candidate, AI invite moves to AI Sent
        r = c.post("/api/candidates", headers=H, json={"first_name": "Test", "last_name": "Person",
                                                        "email": " test.person@example.com ",
                                                        "stage_id": stages["AI Interview Pending"]})
        cid = r.json()["candidate"]["id"]
        assert r.json()["candidate"]["email"] == "test.person@example.com"
        r = c.post(f"/api/candidates/{cid}/email/preview", headers=H, json={"template_id": etpl["ai_invite"]})
        assert "ribbon.ai/interview/37171314" in r.json()["body"], r.text
        assert r.json()["moves_to"] == "AI Interview Sent"
        r = c.post(f"/api/candidates/{cid}/email/send", headers=H, json={"template_id": etpl["ai_invite"]})
        assert r.status_code == 200, r.text
        cand = c.get(f"/api/candidates/{cid}", headers=H).json()["candidate"]
        assert cand["stage_id"] == stages["AI Interview Sent"]

        # pasting the Ribbon link moves to Screening
        r = c.patch(f"/api/candidates/{cid}", headers=H, json={"ai_interview_link": "https://app.ribbon.ai/recruit/interviews/1/abc"})
        assert r.json()["candidate"]["stage_id"] == stages["Screening"], r.text

        # assign department
        r = c.post("/api/candidates/bulk/move", headers=H, json={"ids": [cid], "stage_id": stages["Department Review"],
                                                                 "department_id": depts["ERP-EPM"]})
        assert r.json()["results"][0]["error"] == "", r.text

        # ERP round 2 (has a test)
        t2 = tpls["ERP-EPM - Second Round"]
        r = c.post("/api/interviews/availability", headers=H, json={"candidate_id": cid, "template_id": t2["id"]})
        job = r.json()["job_id"]
        res = c.get(f"/api/interviews/availability/{job}", headers=H).json()
        assert res["status"] == "done" and res["slots"], res
        slot = res["slots"][0]
        d = datetime.fromisoformat(slot["start"])
        assert d.isoweekday() in (1, 5), slot
        assert "mkaur@novamodus.com" in slot["required"]
        mods = meta["modules"]
        r = c.post("/api/interviews/preview", headers=H, json={"candidate_id": cid, "template_id": t2["id"],
                                                               "start": slot["start"], "module_id": mods[2]["id"]})
        pv = r.json()
        assert "{{test_block}}" in pv["body"] and pv["includes_test"], pv
        r = c.post("/api/interviews", headers=H, json={
            "candidate_id": cid, "template_id": t2["id"], "start": slot["start"], "required": slot["required"],
            "optional": slot["optional"], "module_id": mods[2]["id"], "subject": pv["subject"], "body": pv["body"]})
        assert r.status_code == 200, r.text
        iv = r.json()["interview"]
        assert "Username:" in iv["body"] and "Password:" in iv["body"]
        detail = c.get(f"/api/candidates/{cid}", headers=H).json()
        assert detail["interviews"][0]["status"] == "scheduled"
        assert detail["interviews"][0]["outlook_entry_id"].startswith("SIM-")
        kinds = [j["description"] for j in detail["jobs"]]
        assert any("IT access" in k for k in kinds), kinds
        a = detail["assignments"][0]
        pw = iv["body"].split("Password: ")[1].split("\n")[0].strip()

        # reschedule
        new = (d + timedelta(days=7)).isoformat()
        r = c.post(f"/api/interviews/{iv['id']}/reschedule", headers=H, json={"start": new})
        assert r.status_code == 200, r.text

        # candidate portal
        r = c.post("/api/portal/login", json={"username": a["username"], "password": "wrong"})
        assert r.status_code == 401
        r = c.post("/api/portal/login", json={"username": a["username"], "password": pw})
        assert r.status_code == 200, r.text
        CH = {"Authorization": "Bearer " + r.json()["token"]}
        assert c.get("/api/portal/test", headers=CH).status_code == 403  # needs code first
        r = c.post("/api/portal/unlock", headers=CH, json={"code": "000000"})
        assert r.status_code == 400
        code = c.post(f"/api/assignments/{a['id']}/start-code", headers=H).json()["code"]
        r = c.post("/api/portal/unlock", headers=CH, json={"code": code})
        assert r.status_code == 200, r.text
        TH = {"Authorization": "Bearer " + r.json()["token"]}
        # code is one-time
        assert c.post("/api/portal/unlock", headers=CH, json={"code": code}).status_code == 400
        t = c.get("/api/portal/test", headers=TH).json()
        assert t["remaining_seconds"] > 0
        assert all("correct_index" not in q for q in t["questions"])
        for q in t["questions"]:
            if q["kind"] == "mcq":
                assert c.put(f"/api/portal/answers/{q['id']}", headers=TH, json={"value": "1"}).status_code == 200
            else:
                c.put(f"/api/portal/answers/{q['id']}", headers=TH, json={"value": "My answer"})
        c.post("/api/portal/events", headers=TH, json={"type": "fullscreen_exit"})
        c.post("/api/portal/events", headers=TH, json={"type": "paste_blocked"})
        assert c.post("/api/portal/submit", headers=TH).status_code == 200
        assert c.get("/api/portal/test", headers=TH).status_code == 410
        assert c.post("/api/portal/login", json={"username": a["username"], "password": pw}).status_code == 403
        res = c.get(f"/api/assignments/{a['id']}", headers=H).json()
        assert res["status"] == "submitted" and res["auto_score"] is not None
        assert any(e["type"] == "fullscreen_exit" for e in res["events"])
        long_q = [i for i in res["items"] if i["question"]["kind"] == "long"][0]
        r = c.put(f"/api/assignments/{a['id']}/grade", headers=H, json={
            "items": [{"question_id": long_q["question"]["id"], "score": 4, "comment": "good"}], "final": True})
        assert r.status_code == 200, r.text

        # reject with email
        r = c.post("/api/candidates/bulk/move", headers=H, json={"ids": [cid], "stage_id": stages["Rejected"]})
        assert r.json()["results"][0]["emailed"]
        jobs = c.get("/api/jobs", headers=H).json()
        rej = [j for j in jobs if j["description"].startswith("Rejection")][0]
        full = c.get(f"/api/jobs/{rej['id']}", headers=H).json()
        assert "mkaur@novamodus.com" in full["payload"]["cc"] and "areddy@novamodus.com" in full["payload"]["cc"]

        # connector protocol (turn simulation off)
        c.put("/api/settings", headers=H, json={"simulate_outlook": "false"})
        key = c.post("/api/auth/connector-key", headers=H).json()["connector_key"]
        K = {"X-Connector-Key": key}
        assert c.post("/api/connector/heartbeat", headers=K, json={"version": "1"}).status_code == 200
        c.post(f"/api/candidates/{cid}/email/send", headers=H, json={"template_id": etpl["phone_screening"]})
        got = c.get("/api/connector/jobs", headers=K).json()
        assert got and got[0]["kind"] == "send_mail"
        r = c.post(f"/api/connector/jobs/{got[0]['id']}/complete", headers=K, json={"ok": True, "result": {}})
        assert r.status_code == 200
        assert c.get("/api/connector/download", headers=H).status_code == 200

        # department-limited recruiter: a candidate in another department is a read-only summary
        cand_dept = c.get(f"/api/candidates/{cid}", headers=H).json()["candidate"]["department_id"]
        other = [v for v in depts.values() if v != cand_dept][0]
        r = c.post("/api/users", headers=H, json={"name": "Rec", "email": "rec@novamodus.com", "password": "password1",
                                                  "role_ids": [r["id"] for r in meta["roles"] if r["key"] == "recruiter"], "department_ids": [other]})
        assert r.status_code == 200, r.text
        ih = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "rec@novamodus.com", "password": "password1"}).json()["token"]}
        if cand_dept:
            got = c.get(f"/api/candidates/{cid}", headers=ih).json()
            assert got["access"] == "summary" and "email" not in got["candidate"], got
            assert c.post(f"/api/candidates/{cid}/email/send", headers=ih, json={"template_id": etpl["phone_screening"]}).status_code == 403
        assert c.delete(f"/api/candidates/{cid}", headers=ih).status_code == 403
        assert c.put("/api/settings", headers=ih, json={"simulate_outlook": "true"}).status_code == 403

        if WORKBOOK:
            with open(WORKBOOK, "rb") as fh:
                r = c.post("/api/import/preview", headers=H, files={"file": ("Hire.xlsm", fh)})
            assert r.status_code == 200, r.text
            pv = r.json()
            for s in pv["sheets"]:
                print(s["sheet"], s["action"], s["rows"], s.get("already_in_app"))
            choice = [{"sheet": s["sheet"], "action": s["action"], "stage_id": s.get("stage_id"),
                       "department_id": s.get("department_id")} for s in pv["sheets"]]
            r = c.post("/api/import/commit", headers=H, json={"token": pv["token"], "sheets": choice})
            assert r.status_code == 200, r.text
            print(r.json())
            lst = c.get("/api/candidates", headers=H).json()
            print("total", len(lst), "dups", sum(1 for x in lst if x["duplicate"]))
            ams = [x for x in lst if x["first_name"] == "Roseleen"][0]
            print("roseleen module", ams["module_id"], ams["custom"], ams["round1_info"])
            r = c.post("/api/import/commit", headers=H, json={"token": pv["token"], "sheets": choice})
            assert r.status_code == 400  # file consumed
        print("ALL OK")
