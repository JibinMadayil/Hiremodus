import os
import sqlite3
import sys
import tempfile

TMP = tempfile.mkdtemp()
DB = f"{TMP}/old.db"
os.environ["HIREMODUS_DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["HIREMODUS_UPLOAD_DIR"] = f"{TMP}/up"
os.environ["HIREMODUS_IMPORT_DIR"] = f"{TMP}/imp"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# simulate a database from the first release: tables without the new columns
con = sqlite3.connect(DB)
con.execute("CREATE TABLE modules (id INTEGER PRIMARY KEY, name VARCHAR(200), web_link TEXT, training_link TEXT, active BOOLEAN)")
con.execute("CREATE TABLE questions (id INTEGER PRIMARY KEY, test_id INTEGER, kind VARCHAR(10), prompt TEXT, options JSON, correct_index INTEGER, points FLOAT, sort INTEGER)")
con.commit()
con.close()

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def test_extras():
    with TestClient(app) as c:
        cols = {r[1] for r in sqlite3.connect(DB).execute("PRAGMA table_info(questions)")}
        assert "correct_indices" in cols
        # team logins
        for email, pw in [("areddy@novamodus.com", "HM-Anitha-3Rw9!"), ("jmadayil@novamodus.com", "HM-Jibin-7K4p!")]:
            r = c.post("/api/auth/login", json={"email": email, "password": pw})
            assert r.status_code == 200, r.text
            assert r.json()["user"]["must_change_password"]
        H = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "jmadayil@novamodus.com", "password": "HM-Jibin-7K4p!"}).json()["token"]}
        meta = c.get("/api/meta", headers=H).json()
        names = {t["name"] for t in meta["tests"]}
        assert {"Oracle General Ledger - Questionnaire", "Accounts Receivable & Collections - Questionnaire",
                "Oracle Project Management - Questionnaire", "Oracle EPM Planning - Interview Questions"} <= names
        tests = c.get("/api/tests", headers=H).json()
        pts = {t["name"]: t["total_points"] for t in tests}
        assert pts["Accounts Receivable & Collections - Questionnaire"] == 23
        assert pts["Oracle General Ledger - Questionnaire"] == 20
        assert pts["Oracle EPM Planning - Interview Questions"] == 20
        gl_mod = [m for m in meta["modules"] if m["name"] == "ERP - General Ledger"][0]
        assert gl_mod["test_id"]

        # module picks the test on an interview that includes one
        demo = [x for x in c.get("/api/candidates?q=Demo", headers=H).json() if x["first_name"] == "Demo"][0]
        tpl = [t for t in meta["interview_templates"] if t["name"] == "ERP-EPM - Second Round"][0]
        pv = c.post("/api/interviews/preview", headers=H, json={"candidate_id": demo["id"], "template_id": tpl["id"],
                                                                "start": "2026-12-04T10:00:00", "module_id": gl_mod["id"]}).json()
        assert pv["test_name"] == "Oracle General Ledger - Questionnaire", pv

        # demo candidate login + start code + multi grading
        r = c.post("/api/portal/login", json={"username": "Demo.Candidate", "password": "DemoTest2026"})
        assert r.status_code == 200, r.text
        CH = {"Authorization": "Bearer " + r.json()["token"]}
        a = [x for x in c.get("/api/assignments", headers=H).json() if x["username"] == "demo.candidate"][0]
        code = c.post(f"/api/assignments/{a['id']}/start-code", headers=H).json()["code"]
        TH = {"Authorization": "Bearer " + c.post("/api/portal/unlock", headers=CH, json={"code": code}).json()["token"]}
        t = c.get("/api/portal/test", headers=TH).json()
        q1 = t["questions"][0]
        assert q1["kind"] == "multi"
        assert c.put(f"/api/portal/answers/{q1['id']}", headers=TH, json={"value": "4,0,3,2"}).status_code == 200
        q2 = t["questions"][1]
        c.put(f"/api/portal/answers/{q2['id']}", headers=TH, json={"value": "0"})  # wrong
        assert c.put(f"/api/portal/answers/{q1['id']}", headers=TH, json={"value": "9"}).status_code == 400
        c.post("/api/portal/submit", headers=TH)
        res = c.get(f"/api/assignments/{a['id']}", headers=H).json()
        assert res["auto_score"] == 1, res["auto_score"]
        assert res["total_points"] == 20

        # editor accepts multi with checks
        body = {"name": "X", "department_ids": [1], "duration_min": 10, "questions": [
            {"kind": "multi", "prompt": "p", "options": ["a", "b", "c"], "correct_indices": [0, 2], "points": 2}]}
        r = c.post("/api/tests", headers=H, json=body)
        assert r.status_code == 200 and r.json()["questions"][0]["correct_indices"] == [0, 2]
        body["questions"][0]["correct_indices"] = []
        assert c.post("/api/tests", headers=H, json=body).status_code == 400
