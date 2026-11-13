"""Roles by department, transfers, associates, department tests, Excel test papers, integrity snapshots."""
import io
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ["HIREMODUS_DATABASE_URL"] = f"sqlite:///{TMP}/v3.db"
os.environ["HIREMODUS_UPLOAD_DIR"] = f"{TMP}/up"
os.environ["HIREMODUS_IMPORT_DIR"] = f"{TMP}/imp"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

PW = "password1"


def login(c, email, pw=PW):
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_v3():
    with TestClient(app) as c:
        H = login(c, "admin@novamodus.com", "ChangeMe123!")
        meta = c.get("/api/meta", headers=H).json()
        roles = {r["key"]: r["id"] for r in meta["roles"]}
        assert set(roles) >= {"admin", "recruiter", "associate"} and "interviewer" not in roles
        depts = {d["name"]: d["id"] for d in meta["departments"]}
        stages = {s["name"]: s for s in meta["stages"]}
        free_stages = [s for s in meta["stages"] if s["kind"] == "open" and not s["requires_department"]]
        dept_stage = [s for s in meta["stages"] if s["kind"] == "open" and s["requires_department"]][0]
        hcm, scm, erp = depts["HCM"], depts["SCM"], depts["ERP-EPM"]

        def mk(email, role_keys, dept_ids=()):
            r = c.post("/api/users", headers=H, json={"name": email.split("@")[0].title(), "email": email, "password": PW,
                                                      "role_ids": [roles[k] for k in role_keys], "department_ids": list(dept_ids)})
            assert r.status_code == 200, r.text
            return login(c, email)

        RH = mk("hcm.rec@novamodus.com", ["recruiter"], [hcm])
        RS = mk("scm.rec@novamodus.com", ["recruiter"], [scm])
        AS = mk("assoc@novamodus.com", ["associate"])
        AD = mk("pure.admin@novamodus.com", ["admin"])

        # associate adds a candidate, works the early stages, can't jump into a department stage
        r = c.post("/api/candidates", headers=AS, json={"first_name": "Asha", "last_name": "Early", "email": "asha@example.com"})
        assert r.status_code == 200, r.text
        cid = r.json()["candidate"]["id"]
        assert c.post("/api/candidates", headers=AS, json={"first_name": "No", "stage_id": dept_stage["id"]}).status_code == 403
        res = c.post("/api/candidates/bulk/move", headers=AS, json={"ids": [cid], "stage_id": free_stages[-1]["id"], "send_email": False}).json()
        assert not res["results"][0]["error"], res
        res = c.post("/api/candidates/bulk/move", headers=AS, json={"ids": [cid], "stage_id": dept_stage["id"], "department_id": hcm, "send_email": False}).json()
        assert "associates" in res["results"][0]["error"]
        assert c.get("/api/tests", headers=AS).status_code == 403
        # hand-off to HCM notifies the HCM recruiter, after which the associate only sees a summary
        res = c.post("/api/candidates/bulk/move", headers=AS, json={"ids": [cid], "department_id": hcm, "send_email": False}).json()
        assert not res["results"][0]["error"], res
        assert any("New candidate for HCM" in n["title"] for n in c.get("/api/notifications", headers=RH).json()["items"])
        assert c.get(f"/api/candidates/{cid}", headers=AS).json()["access"] == "summary"
        assert c.patch(f"/api/candidates/{cid}", headers=AS, json={"notes": "x"}).status_code in (403, 404)

        # HCM recruiter: full access; SCM recruiter: summary only, defaults to own departments
        assert c.get(f"/api/candidates/{cid}", headers=RH).json()["access"] == "full"
        got = c.get(f"/api/candidates/{cid}", headers=RS).json()
        assert got["access"] == "summary" and "email" not in got["candidate"]
        mine = c.get("/api/candidates?mine=true", headers=RS).json()
        assert all(x["id"] != cid for x in mine)
        everyone = c.get("/api/candidates?mine=false", headers=RS).json()
        row = [x for x in everyone if x["id"] == cid][0]
        assert row["access"] == "summary" and "email" not in row
        assert c.get("/api/candidates/search?q=Asha", headers=RS).json()[0]["email"] == ""

        # direct department edit can't skip the transfer note
        r = c.patch(f"/api/candidates/{cid}", headers=RH, json={"department_id": scm})
        assert r.status_code == 400 and "Transfer" in r.text
        assert c.post(f"/api/candidates/{cid}/transfer", headers=RH, json={"to_department_id": scm, "note": " "}).status_code == 400
        tid = c.post(f"/api/candidates/{cid}/transfer", headers=RH, json={"to_department_id": scm, "note": "Better fit for SCM"}).json()["id"]
        assert any("Transfer request" in n["title"] for n in c.get("/api/notifications", headers=RS).json()["items"])
        # while pending the receiving recruiter can open the full profile; the sender can't accept
        assert c.get(f"/api/candidates/{cid}", headers=RS).json()["access"] == "full"
        assert c.post(f"/api/candidates/transfers/{tid}/accept", headers=RH).status_code == 403
        dash = c.get("/api/dashboard", headers=RS).json()
        assert any(t["id"] == tid for t in dash["transfers"])
        assert c.post(f"/api/candidates/transfers/{tid}/accept", headers=RS).status_code == 200
        assert c.get(f"/api/candidates/{cid}", headers=RS).json()["candidate"]["department_id"] == scm
        assert c.get(f"/api/candidates/{cid}", headers=RH).json()["access"] == "summary"

        # transfer back and decline: candidate rejected, rejection email queued
        tid2 = c.post(f"/api/candidates/{cid}/transfer", headers=RS, json={"to_department_id": hcm, "note": "Try HCM"}).json()["id"]
        r = c.post(f"/api/candidates/transfers/{tid2}/decline", headers=RH, json={"note": "No opening", "send_email": True}).json()
        cand = c.get(f"/api/candidates/{cid}", headers=H).json()
        rejected = [s for s in meta["stages"] if s["kind"] == "rejected"][0]
        assert cand["candidate"]["stage_id"] == rejected["id"]
        assert [t["status"] for t in cand["transfers"]][:2] == ["declined", "accepted"] or \
            sorted(t["status"] for t in cand["transfers"]) == ["accepted", "declined"]
        assert c.post(f"/api/candidates/transfers/{tid2}/accept", headers=RH).status_code == 400

        # CC list grants department access
        assert c.put(f"/api/admin/departments/{erp}", headers=H, json={"cc_emails": "hcm.rec@novamodus.com"}).status_code == 200
        cid2 = c.post("/api/candidates", headers=H, json={"first_name": "Erin", "last_name": "Epm", "department_id": erp}).json()["candidate"]["id"]
        assert c.get(f"/api/candidates/{cid2}", headers=RH).json()["access"] == "full"

        # tests are per department; plain admin sees no papers
        assert c.get("/api/tests", headers=AD).status_code == 403
        rh_tests = c.get("/api/tests", headers=RH).json()
        assert rh_tests and all(set(t["department_ids"]) & {hcm, erp} for t in rh_tests)
        rs_tests = c.get("/api/tests", headers=RS).json()
        only_erp = [t for t in rh_tests if set(t["department_ids"]) == {erp}]
        if only_erp:
            assert all(t["id"] != only_erp[0]["id"] for t in rs_tests)
            assert c.get(f"/api/tests/{only_erp[0]['id']}", headers=RS).status_code == 403
        body = {"name": "SCM only", "department_ids": [scm], "questions": [{"kind": "short", "prompt": "x"}]}
        assert c.post("/api/tests", headers=RH, json=body).status_code == 403
        assert c.post("/api/tests", headers=RS, json=body).status_code == 200
        assert c.post("/api/tests", headers=RS, json={**body, "department_ids": []}).status_code == 400

        # Excel template: download, preview, create new, add, replace
        r = c.get("/api/test-paper/template.xlsx", headers=RH)
        assert r.status_code == 200 and r.content[:2] == b"PK"
        assert c.get("/api/test-paper/template.xlsx", headers=AD).status_code == 403
        tpl = r.content
        pv = c.post("/api/test-paper/preview", headers=RS, files={"file": ("p.xlsx", tpl)}).json()
        assert any("don't work in ERP-EPM" in e for e in pv["errors"])  # the sample is for ERP-EPM
        pv = c.post("/api/test-paper/preview", headers=RH, files={"file": ("p.xlsx", tpl)}).json()
        assert pv["errors"] == [], pv["errors"]
        assert len(pv["questions"]) == 7 and pv["pictures"] == 5
        apt = [q for q in pv["questions"] if q["image"]][0]
        assert all(apt["option_images"]) and c.get(apt["image"]).status_code == 200
        t = c.post("/api/test-paper/commit", headers=RH, json={"mode": "new", "details": pv["details"], "questions": pv["questions"]})
        assert t.status_code == 200, t.text
        t = t.json()
        assert t["allow_file_upload"] and len(t["questions"]) == 7 and t["department_ids"] == [erp]
        t2 = c.post("/api/test-paper/commit", headers=RH, json={"mode": "add", "test_id": t["id"], "questions": pv["questions"][:2]}).json()
        assert len(t2["questions"]) == 9
        t3 = c.post("/api/test-paper/commit", headers=RH, json={"mode": "replace", "test_id": t["id"], "questions": pv["questions"][4:5]}).json()
        assert len(t3["questions"]) == 1 and t3["questions"][0]["kind"] == "short"
        assert c.post("/api/test-paper/commit", headers=RS, json={"mode": "add", "test_id": t["id"], "questions": pv["questions"][:1]}).status_code == 403
        bad = c.post("/api/test-paper/preview", headers=RH, files={"file": ("p.xlsx", b"not excel")}).json()
        assert bad["errors"]

        # integrity snapshot during a test, shown on the result with a signed link
        cid3 = c.post("/api/candidates", headers=H, json={"first_name": "Snap", "last_name": "Shot", "email": "snap@example.com", "department_id": erp}).json()["candidate"]["id"]
        asg = c.post(f"/api/candidates/{cid3}/assign-test", headers=RH, json={"test_id": t["id"], "send_email": False}).json()
        a = asg["assignment"]
        CH = {"Authorization": "Bearer " + c.post("/api/portal/login", json={"username": a["username"], "password": asg["password"]}).json()["token"]}
        st = c.get("/api/portal/state", headers=CH).json()
        assert st["integrity"]["quality"] == "high" and st["integrity"]["detect"]
        code = c.post(f"/api/assignments/{a['id']}/start-code", headers=RH).json()["code"]
        TH = {"Authorization": "Bearer " + c.post("/api/portal/unlock", headers=CH, json={"code": code}).json()["token"]}
        assert c.post("/api/portal/events", headers=TH, json={"type": "phone_detected", "detail": "cell phone 82%"}).status_code == 200
        assert c.post("/api/portal/snapshot?kind=phone_detected&detail=82%25", headers=TH, content=b"\xff\xd8JPEG").status_code == 200
        assert c.post("/api/portal/snapshot?kind=bogus", headers=TH, content=b"x").status_code == 400
        res = c.get(f"/api/assignments/{a['id']}", headers=RH).json()
        snap = res["snapshots"][0]
        assert snap["kind"] == "phone_detected" and c.get(snap["url"]).content == b"\xff\xd8JPEG"
        assert any(e["type"] == "phone_detected" for e in res["events"])
        # an out-of-department recruiter can't open the result
        assert c.get(f"/api/assignments/{a['id']}", headers=RS).status_code in (403, 404)

        # settings: recording quality is admin-editable
        assert c.put("/api/settings", headers=H, json={"recording_quality": "standard"}).json()["recording_quality"] == "standard"
        assert c.put("/api/settings", headers=H, json={"recording_quality": "ultra"}).status_code == 400
        assert c.put("/api/settings", headers=RH, json={"recording_quality": "low"}).status_code == 403
