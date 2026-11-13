"""Candidate replies (connector and Graph), replying from HireModus, department dashboards, interview feedback,
clearing out old candidate data, and Microsoft 365 sign-in and mail, against a simulated Microsoft service."""
import base64
import os
import sys
import tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ["HIREMODUS_DATABASE_URL"] = f"sqlite:///{TMP}/v4.db"
os.environ["HIREMODUS_UPLOAD_DIR"] = f"{TMP}/up"
os.environ["HIREMODUS_IMPORT_DIR"] = f"{TMP}/imp"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app import models, msgraph, graphworker, retention  # noqa: E402
from app.db import SessionLocal  # noqa: E402

PW = "password1"


def login(c, email, pw=PW):
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def connector(c, H):
    key = c.post("/api/auth/connector-key", headers=H).json()["connector_key"]
    return {"X-Connector-Key": key}


def msg(frm, subject, body, mid, minutes_ago=5, entry="E1", atts=()):
    return {"entry_id": entry, "message_id": mid, "from": frm, "from_name": "Cand", "to": "x@novamodus.com", "cc": "",
            "subject": subject, "received_at": (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat() + "Z",
            "body": body, "attachments": list(atts)}


def test_v4():
    with TestClient(app) as c:
        H = login(c, "admin@novamodus.com", "ChangeMe123!")
        c.put("/api/settings", headers=H, json={"simulate_outlook": "false"})
        meta = c.get("/api/meta", headers=H).json()
        roles = {r["key"]: r["id"] for r in meta["roles"]}
        depts = {d["name"]: d["id"] for d in meta["departments"]}
        stages = {s["kind"]: s["id"] for s in meta["stages"] if s["kind"] != "open"}
        hcm, scm = depts["HCM"], depts["SCM"]
        c.put(f"/api/admin/departments/{hcm}", headers=H, json={"cc_emails": "cc.person@novamodus.com"})

        def mk(email, keys, d=()):
            r = c.post("/api/users", headers=H, json={"name": email.split("@")[0], "email": email, "password": PW,
                                                      "role_ids": [roles[k] for k in keys], "department_ids": list(d)})
            assert r.status_code == 200, r.text
            return login(c, email)

        RH = mk("rec.hcm@novamodus.com", ["recruiter"], [hcm])
        CC = mk("cc.person@novamodus.com", ["recruiter"])  # gets HCM through the CC list
        RS = mk("rec.scm@novamodus.com", ["recruiter"], [scm])
        cid = c.post("/api/candidates", headers=H, json={"first_name": "Rita", "last_name": "Reply", "email": "rita@example.com",
                                                         "department_id": hcm}).json()["candidate"]["id"]
        other = c.post("/api/candidates", headers=H, json={"first_name": "Sam", "last_name": "Scm", "email": "sam@example.com",
                                                           "department_id": scm}).json()["candidate"]["id"]
        db = SessionLocal()
        db.get(models.Candidate, cid).clock_started_at = datetime.utcnow() - timedelta(days=20)
        db.commit()

        # ---- connector picks up a reply
        K = connector(c, RH)
        w = c.get("/api/connector/watch", headers=K).json()
        assert w["enabled"] and "rita@example.com" in w["addresses"] and "sam@example.com" not in w["addresses"]
        assert datetime.fromisoformat(w["since"][:-1]) < datetime.utcnow() - timedelta(days=29)  # first look-back
        pdf = base64.b64encode(b"%PDF resume").decode()
        r = c.post("/api/connector/replies", headers=K, json={"scanned_at": datetime.utcnow().isoformat() + "Z", "messages": [
            msg("Rita@Example.com", "RE: Interview", "Thanks, Tuesday works.\n\nOn Mon, X wrote:\n> old text", "<m1@ex>",
                atts=[{"name": "resume.pdf", "size": 11, "content_b64": pdf}, {"name": "big.mov", "size": 99999999, "content_b64": ""}]),
            msg("stranger@example.com", "Hi", "spam", "<m2@ex>"),
        ]}).json()
        assert r == {"stored": 1, "copies": 0, "skipped": 1}
        assert datetime.fromisoformat(c.get("/api/connector/watch", headers=K).json()["since"][:-1]) > datetime.utcnow() - timedelta(minutes=15)
        # the same email in the CC person's inbox is stored once
        K2 = connector(c, CC)
        r = c.post("/api/connector/replies", headers=K2, json={"scanned_at": datetime.utcnow().isoformat() + "Z",
                                                                 "messages": [msg("rita@example.com", "RE: Interview", "Thanks", "<m1@ex>", entry="CCE")]}).json()
        assert r["stored"] == 0 and r["copies"] == 1
        # alerts for the department, aging clock restarted, preview stops at the quote
        assert any("Rita Reply replied" in n["title"] for n in c.get("/api/notifications", headers=RH).json()["items"])
        assert any("Rita Reply replied" in n["title"] for n in c.get("/api/notifications", headers=CC).json()["items"])
        assert not any("Rita" in n["title"] for n in c.get("/api/notifications", headers=RS).json()["items"])
        db.expire_all()
        assert db.get(models.Candidate, cid).clock_started_at > datetime.utcnow() - timedelta(hours=1)
        detail = c.get(f"/api/candidates/{cid}", headers=RH).json()
        e = detail["emails"][0]
        assert e["preview"] == "Thanks, Tuesday works." and e["unread"] and e["in_my_inbox"]
        assert [a["available"] for a in e["attachments"]] == [True, False]
        # unread on the list and the dashboard, per person
        row = [x for x in c.get("/api/candidates?mine=true", headers=RH).json() if x["id"] == cid][0]
        assert row["unread_replies"] == 1
        assert [x["id"] for x in c.get("/api/candidates?unread_only=true", headers=RH).json()] == [cid]
        dash = c.get(f"/api/dashboard?department_id={hcm}", headers=RH).json()
        assert dash["unread_replies"] == 1 and dash["replies"][0]["candidate_id"] == cid
        assert c.get(f"/api/dashboard?department_id={scm}", headers=RH).status_code == 403
        assert c.get(f"/api/aging?department_id={hcm}", headers=RH).status_code == 200
        assert c.get(f"/api/dashboard?department_id={scm}", headers=H).json()["unread_replies"] == 0
        # reading: full text, attachment download, marks read for that person only
        full = c.get(f"/api/candidate-emails/{e['id']}", headers=RH).json()
        assert "Tuesday works" in full["body"] and "old text" in full["body"]
        assert c.get(f"/api/candidate-emails/{e['id']}/attachments/0", headers=RH).content == b"%PDF resume"
        assert c.get(f"/api/candidate-emails/{e['id']}/attachments/1", headers=RH).status_code == 404
        assert c.get(f"/api/candidate-emails/{e['id']}", headers=RS).status_code == 403
        assert c.get(f"/api/dashboard", headers=RH).json()["unread_replies"] == 0
        assert c.get(f"/api/dashboard", headers=CC).json()["unread_replies"] == 1

        # ---- replying from HireModus
        d = c.get(f"/api/candidate-emails/{e['id']}/reply-draft", headers=CC).json()
        assert d["to"] == "rita@example.com" and d["subject"] == "RE: Interview" and d["threaded"] and d["via"] == "connector"
        assert c.post(f"/api/candidate-emails/{e['id']}/reply", headers=CC, json={"body": " "}).status_code == 400
        r = c.post(f"/api/candidate-emails/{e['id']}/reply", headers=CC, json={"body": "See you Tuesday.", "cc": "rec.hcm@novamodus.com"}).json()
        assert r["threaded"]
        jobs = c.get("/api/connector/jobs", headers=K2).json()
        j = [x for x in jobs if x["kind"] == "reply_mail"][0]
        assert j["payload"]["entry_id"] == "CCE" and j["payload"]["to"] == "rita@example.com"
        assert "> Thanks" in j["payload"]["quoted"] and j["payload"]["cc"] == "rec.hcm@novamodus.com"
        c.post(f"/api/connector/jobs/{j['id']}/complete", headers=K2, json={"ok": True, "result": {"threaded": True}})
        sent = [x for x in c.get(f"/api/candidates/{cid}", headers=RH).json()["jobs"] if x["kind"] == "reply_mail"][0]
        assert sent["status"] == "done" and sent["threaded"] and sent["reply_to"] == e["id"]
        # someone without the email in their inbox sends a new email with the message quoted
        RA = mk("rec.hcm2@novamodus.com", ["recruiter"], [hcm])
        d = c.get(f"/api/candidate-emails/{e['id']}/reply-draft", headers=RA).json()
        assert not d["threaded"] and d["dept_cc"] == "cc.person@novamodus.com"
        assert not c.post(f"/api/candidate-emails/{e['id']}/reply", headers=RA, json={"body": "Hello"}).json()["threaded"]

        # ---- interview feedback
        qs = c.get("/api/feedback/questions", headers=RH).json()
        assert [q["label"] for q in qs][:2] == ["Overall rating", "Recommendation"]
        db = SessionLocal()
        iv = models.Interview(candidate_id=cid, title="Round 1", start=datetime.now() - timedelta(hours=2), end=datetime.now() - timedelta(hours=1),
                              status="scheduled")
        db.add(iv)
        db.commit()
        rating, rec = str(qs[0]["id"]), str(qs[1]["id"])
        assert c.post(f"/api/interviews/{iv.id}/feedback", headers=RH, json={"answers": {rating: "4"}}).status_code == 400
        assert c.post(f"/api/interviews/{iv.id}/feedback", headers=RH, json={"answers": {rating: "9", rec: "Hire"}}).status_code == 400
        assert c.post(f"/api/interviews/{iv.id}/feedback", headers=RH, json={"answers": {rating: "4", rec: "Hire", str(qs[2]["id"]): "Clear on SLA"}}).status_code == 200
        assert c.post(f"/api/interviews/{iv.id}/feedback", headers=RH, json={"answers": {rating: "5", rec: "Hire"}}).status_code == 200  # edit, not a second one
        assert c.post(f"/api/interviews/{iv.id}/feedback", headers=RS, json={"answers": {rating: "1", rec: "No hire"}}).status_code == 403
        fb = c.get(f"/api/candidates/{cid}", headers=CC).json()["feedback"]
        assert len(fb) == 1 and fb[0]["answers"][rating] == "5"
        summ = c.get(f"/api/candidates/{cid}", headers=RS).json()
        assert summ["access"] == "summary" and summ["candidate"]["feedback_count"] == 1 and "feedback" not in summ
        assert c.post("/api/feedback/questions", headers=RH, json={"label": "x"}).status_code == 403
        assert c.post("/api/feedback/questions", headers=H, json={"label": "Communication", "kind": "rating"}).json()["options"] == ["1", "2", "3", "4", "5"]

        # ---- clearing out old candidate data
        assert c.put("/api/settings", headers=H, json={"retention_enabled": "true", "retention_months": "12"}).status_code == 200
        db = SessionLocal()
        cand = db.get(models.Candidate, cid)
        cand.stage_id = stages["rejected"]
        cand.stage_changed_at = datetime.utcnow() - timedelta(days=400)
        keep = db.get(models.Candidate, other)
        keep.stage_id, keep.stage_changed_at, keep.retention_keep = stages["withdrawn"], datetime.utcnow() - timedelta(days=400), True
        db.commit()
        assert retention.run(db) == {"warned": 1, "cleared": 0}  # warning first
        assert any("will have their details removed" in n["title"] for n in c.get("/api/notifications", headers=H).json()["items"])
        assert c.get("/api/retention", headers=H).json()["upcoming"][0]["id"] == cid
        assert c.get("/api/retention", headers=RH).status_code == 403
        db.get(models.Candidate, cid).retention_warned_at = datetime.utcnow() - timedelta(days=15)
        db.commit()
        email_ids = [x.id for x in db.query(models.CandidateEmail).filter_by(candidate_id=cid)]
        assert retention.run(db) == {"warned": 0, "cleared": 1}
        db.expire_all()
        gone = db.get(models.Candidate, cid)
        assert gone.email == "" and gone.first_name == "Removed candidate" and gone.anonymized_at and gone.department_id == hcm
        assert not db.query(models.CandidateEmail).filter_by(candidate_id=cid).count()
        assert not os.path.exists(os.path.join(TMP, "up", "mail", str(email_ids[0])))
        assert not db.query(models.Feedback).filter_by(candidate_id=cid).count()
        assert db.get(models.Candidate, other).email == "sam@example.com"  # kept
        assert "rita@example.com" not in c.get("/api/connector/watch", headers=K).json()["addresses"]

        # ---- Microsoft 365: settings
        assert c.put("/api/microsoft/settings", headers=H, json={"ms_graph_enabled": "true"}).status_code == 400  # not configured
        s = c.put("/api/microsoft/settings", headers=H, json={"ms_tenant_id": "tid-1", "ms_client_id": "app-1", "ms_client_secret": "S3CRET",
                                                               "ms_graph_enabled": "true", "ms_default_transport": "connector"}).json()
        assert s["configured"] and s["secret_set"] and "S3CRET" not in str(s)
        assert "S3CRET" not in str(c.get("/api/settings", headers=H).json())
        assert c.put("/api/settings", headers=H, json={"ms_client_id": "hijack"}).json().get("ms_client_id") == "app-1"
        assert c.put("/api/microsoft/settings", headers=H, json={"ms_public_url": "http://hiremodus.local"}).status_code == 400

        # ---- simulated Microsoft Graph
        calls = []
        cid3 = c.post("/api/candidates", headers=H, json={"first_name": "Gina", "last_name": "Graph", "email": "gina@example.com",
                                                          "department_id": hcm}).json()["candidate"]["id"]

        def fake_request(method, url, token, json=None, headers=None):
            calls.append((method, url, json))
            if "/mailFolders/inbox/messages" in url:
                return {"value": [
                    {"id": "G1", "internetMessageId": "<g1@ex>", "subject": "Question", "from": {"emailAddress": {"address": "gina@example.com", "name": "Gina"}},
                     "toRecipients": [{"emailAddress": {"address": "rec.hcm@novamodus.com"}}], "ccRecipients": [],
                     "receivedDateTime": datetime.utcnow().isoformat() + "Z", "body": {"content": "Is the role remote?"}, "hasAttachments": True},
                    {"id": "G2", "internetMessageId": "<g2@ex>", "subject": "Newsletter", "from": {"emailAddress": {"address": "news@example.com"}},
                     "receivedDateTime": datetime.utcnow().isoformat() + "Z", "body": {"content": "x"}, "hasAttachments": False}]}
            if url.endswith("/attachments"):
                return {"value": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": "cv.docx", "size": 4, "contentBytes": base64.b64encode(b"DOCX").decode()}]}
            if "/events" in url and method == "POST" and not url.endswith("/cancel"):
                return {"id": "EV1"}
            return {}

        msgraph._request = fake_request
        msgraph._token = lambda cfg: "TOKEN"
        assert c.put("/api/me/mail-transport", headers=RH, json={"mail_transport": "graph"}).json()["uses"] == "graph"
        assert c.get("/api/connector/jobs", headers=K).json() == []  # connector stands down for people on Graph
        assert not c.get("/api/connector/watch", headers=K).json()["enabled"]
        db = SessionLocal()
        users = graphworker.graph_users(db)
        assert [u.email for u in users] == ["rec.hcm@novamodus.com"]
        assert graphworker.check_replies(db, users, force=True) == 1
        g = db.query(models.CandidateEmail).filter_by(candidate_id=cid3).one()
        assert g.copies[str(users[0].id)] == {"via": "graph", "id": "G1"} and g.attachments[0]["name"] == "cv.docx"
        r = c.post(f"/api/candidate-emails/{g.id}/reply", headers=RH, json={"body": "Hybrid, 2 days a week."}).json()
        assert r["threaded"]
        email = c.post(f"/api/candidates/{cid3}/email/send", headers=RH, json={"template_id": meta["email_templates"][0]["id"]})
        db = SessionLocal()
        graphworker.send_jobs(db, graphworker.graph_users(db))
        assert any(m == "POST" and u.endswith("/messages/G1/reply") and j["comment"].startswith("Hybrid") for m, u, j in calls)
        if email.status_code == 200:
            assert any(u.endswith("/users/rec.hcm@novamodus.com/sendMail") for _, u, _ in calls)
        db = SessionLocal()
        assert all(j.status == "done" for j in db.query(models.OutboxJob).filter_by(owner_id=users[0].id).all())
        # a failure stays visible and isn't retried by itself
        msgraph._request = lambda *a, **k: (_ for _ in ()).throw(msgraph.GraphError("ErrorAccessDenied: denied"))
        c.post(f"/api/candidate-emails/{g.id}/reply", headers=RH, json={"body": "again"})
        db = SessionLocal()
        graphworker.send_jobs(db, graphworker.graph_users(db))
        failed = db.query(models.OutboxJob).filter_by(status="failed", owner_id=users[0].id).one()
        assert "Microsoft 365" in failed.error
        msgraph._request = fake_request

        # ---- Microsoft sign-in
        c.put("/api/microsoft/settings", headers=H, json={"ms_signin_enabled": "true", "ms_password_signin": "admins"})
        assert c.get("/api/auth/options").json() == {"microsoft": True, "password": "admins"}
        assert c.post("/api/auth/login", json={"email": "rec.scm@novamodus.com", "password": PW}).status_code == 403
        assert c.post("/api/auth/login", json={"email": "admin@novamodus.com", "password": "ChangeMe123!"}).status_code == 200
        msgraph.start_signin = lambda db, base: "https://login.microsoftonline.com/fake"
        r = c.get("/api/auth/microsoft/start", follow_redirects=False)
        assert r.headers["location"].startswith("https://login.microsoftonline.com/")
        msgraph.finish_signin = lambda db, params: {"oid": "OID-SCM", "tid": "tid-1", "email": "rec.scm@novamodus.com", "name": "x"}
        r = c.get("/api/auth/microsoft/callback?code=abc&state=s", follow_redirects=False)
        tok = r.headers["location"].split("#ms_token=")[1]
        me = c.get("/api/auth/me", headers={"Authorization": "Bearer " + tok}).json()
        assert me["email"] == "rec.scm@novamodus.com" and me["signed_in_with_microsoft"]
        # matched by Microsoft account id afterwards, even if the email in Microsoft changes
        msgraph.finish_signin = lambda db, params: {"oid": "OID-SCM", "tid": "tid-1", "email": "renamed@novamodus.com", "name": "x"}
        assert "#ms_token=" in c.get("/api/auth/microsoft/callback?code=abc&state=s", follow_redirects=False).headers["location"]
        msgraph.finish_signin = lambda db, params: {"oid": "OID-NEW", "tid": "tid-1", "email": "stranger@novamodus.com", "name": "x"}
        loc = c.get("/api/auth/microsoft/callback?code=abc&state=s", follow_redirects=False).headers["location"]
        assert "#ms_error=" in loc and "isn" in loc
        assert any(a["action"] == "microsoft_sign_in_refused" for a in c.get("/api/audit", headers=H).json())
