"""Added on top of the first-run seed, and also applied once to databases created before these existed:
the four Microsoft Forms questionnaires as HireModus tests, team logins, and a demo candidate."""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .security import hash_password
from .services import get_setting, set_setting

FLAG = "seed_extras_v1"

INSTRUCTIONS = ("Multiple choice questions are marked automatically. Where a question says to pick more than one "
                "answer, you need every correct option and nothing else to get the points. Written answers are "
                "reviewed by the interview panel. Answers save as you go and the test submits itself when time runs out.")


def mcq(prompt, options, correct, points=1):
    return dict(kind="mcq", prompt=prompt, options=options, correct_index=correct, points=points)


def multi(prompt, options, correct, points=1):
    return dict(kind="multi", prompt=prompt, options=options, correct_indices=correct, points=points)


def short(prompt, points=1):
    return dict(kind="long", prompt=prompt, points=points)


PROJECTS = dict(name="Oracle Project Management - Questionnaire", duration_min=40, module="ERP - Projects", questions=[
    mcq("When duplicating a template with the same business unit, what assignments can get duplicated too?",
        ["Duplicate the budget", "Duplicate Forecasts", "Duplicate Project Task", "All the above"], 3),
    mcq("Can project dates be outside of the earliest task start date and latest task end date?",
        ["Yes, if you select not to automatically roll up task dates at the project plan type level",
         "Yes, if you select yes to automatically roll up task dates at the project plan type level",
         "No, if you select not to automatically roll up task dates at the project plan type level",
         "No, if you select yes to automatically roll up task dates at the project plan type level"], 0),
    mcq("Who receives the approval notifications related to project changes, updates, and key decisions when there are multiple project managers?",
        ["The primary project manager receives approval notifications related to the project's financial reports, but not other aspects",
         "Approval notifications are sent to all project managers on the team, but the primary project manager is the only one authorized to act on them",
         "Only the primary project manager receives approval notifications related to project changes, updates, and key decisions",
         "Approval notifications are sent to all stakeholders, with no specific role receiving exclusive notifications for project approvals"], 2),
    mcq("What's the difference between the project unit organization code and name?",
        ["The project unit organization code is a unique identifier used internally, while the name is a descriptive, easily recognizable label",
         "The project unit organization code is used for financial transactions, while the project unit name is only used for reporting purposes",
         "The project unit organization code is a descriptive name, while the name serves as a unique identifier for the organization",
         "The project unit organization code and name are interchangeable and serve the same purpose"], 0),
    mcq("What cannot be a commitment transaction?",
        ["A purchase requisition or purchase order charged to a project",
         "A project transaction that has been invoiced and transferred to Oracle Fusion Project Costing",
         "An outstanding purchase order charged to a project that has not been invoiced",
         "None of the above"], 1),
    mcq("Choose one Oracle module from which we cannot import costs into the project.",
        ["Oracle Time & Labor", "Purchasing", "Order Management", "Inventory"], 2),
    mcq("What adjustment can be performed while performing mass adjustment on multiple expenditure items?",
        ["Split", "Transfer", "Split & Transfer", "Edit Comment"], 1),
    mcq("What is the data security level for the project accountant role?",
        ["Business Unit", "Project Unit", "Project Organization", "Assigned Projects", "Cost Organization"], 0),
    mcq("Which configuration allows you to decide about using common or separate accounting and project accounting periods?",
        ["Project Type", "Project Template", "Configure project accounting business function", "Project unit"], 2),
    short("Differentiate burden cost and raw cost."),
    short("Explain budgetary control and its control levels (any 2)."),
    short("What happens if I close an accounting or project accounting period permanently?"),
    short("Explain Project Type and its use in the Project module."),
    short("Explain the use of capital projects and of asset lines."),
    short('In Oracle Fusion PPM, what does the "Project Performance Reporting" feature help with?'),
    short("What are Expenditure types?"),
    short("Explain what a business unit is."),
])

AR = dict(name="Accounts Receivable & Collections - Questionnaire", duration_min=45,
          module="ERP - Accounts Receivable & Collections", questions=[
    mcq("An organization wants to exclude certain customers so that no dunning letters are sent to them. How can this be achieved?",
        ["Disable Send Dunning Letter in Transaction Source Type", "Disable Send Dunning Letter on the Correspondence tab",
         "Disable Send Dunning Letter in Collections Preferences", "Disable Send Dunning Letter on the Profile tab",
         "Disable Send Dunning Letter in Transaction Type"], 3),
    multi("The Accounts Receivables Specialist role includes which two of the following duties? (Select 2)",
          ["Import Payables Invoices Duty", "Receipt Creation Duty", "Trading Community Hierarchy Management Duty",
           "Payment Settlement Management Duty"], [1, 2], 2),
    mcq("To associate multiple Legal Entities with a single Ledger, all of the following must be common across all Legal Entities, except:",
        ["Currency", "Chart of Accounts", "Intercompany Balancing Rules", "Calendar", "Accounting Convention"], 2),
    multi("Which two determinant types are used in reference data assignment? (Select 2)",
          ["Business Unit", "Account Segment", "Project Segment", "Project Unit"], [0, 3], 2),
    mcq("Which of the following statements is true about the AutoInvoice program?",
        ["Transactions are transferred to General Ledger where the account assignments are made",
         "AutoAccounting setup determines the default General Ledger account assignments for the transactions",
         "AutoInvoice does not process invoice lines without a general ledger account assignment. The GL accounts have to be available in the source transaction itself",
         "AutoInvoice processes only transaction information, and general ledger account assignments are made by running another ESS process"], 1),
    multi("What are the two main tabs in Receivables System Options? (Select 2)",
          ["Billing and Revenue", "AutoAccounting Parameters", "Cash Processing", "Accounting Rule Set", "AutoInvoicing"], [0, 2]),
    mcq("If the Cash Management module is used for cash reconciliation for certain receipt classes, which clearance method should be defined in the receipt class?",
        ["Direct", "Automatic Clearing", "By Matching"], 2),
    multi('Which four output file types are available when you run the "Print Receivables Transactions" program? (Select 4)',
          ["HTML", "Excel", "Zipped PDFs", "PDF", "JPG", "Word"], [0, 1, 2, 3], 2),
    mcq("Which information does the collector see after clicking on the Activities infotile in the Collections work area?",
        ["List of delinquent customers", "List of broken payment promises", "Tasks assigned to the collector, such as follow-up calls"], 2),
    mcq("Identify the dunning letter template set provided by Oracle.",
        ["Regular, final demand, medium", "Final demand, soft, medium, hard", "Regular, medium, hard, soft", "Soft, regular, hard, final demand"], 1),
    short("Explain Receipt Classes."),
    short("What are Payment Terms used for?"),
    short("What is a Balance Forward Bill?"),
    short("When are receipts reversed?"),
    short("What are the different document types for which we can define approval limits?"),
    short("What is the difference between standard and miscellaneous receipts?"),
    short("The receipt must be in which status to create a refund?"),
    short("What is a Recurring Bill Plan?"),
    short("What are the different types of adjustment a user can perform in Receivables? Name any three."),
    short("Why does the Collections dashboard fail to display delinquent customers?"),
])

GL = dict(name="Oracle General Ledger - Questionnaire", duration_min=40, module="ERP - General Ledger", questions=[
    multi("Which four components must be defined to create a complete Ledger in Oracle Fusion General Ledger? (Select 4)",
          ["Chart of Accounts", "Legal Entity", "Accounting Calendar", "Accounting Method", "Ledger Currency"], [0, 2, 3, 4]),
    mcq("Your client wants to use a single Chart of Accounts for multiple ledgers. What must be common across all ledgers?",
        ["Accounting Calendar", "Currency", "Chart of Accounts structure", "Accounting Methods"], 2),
    mcq("When defining a Journal Entry Rule Set for Subledger Accounting, which of the following options are available?",
        ["Supporting References", "Journal Line Rules", "Description Rules", "All of the above"], 3),
    mcq("What is the purpose of the Journal Import process in Oracle Fusion General Ledger?",
        ["To approve journal batches", "To transfer journal entries from external systems into General Ledger",
         "To reconcile bank statements", "To generate financial reports"], 1),
    mcq("What is the correct order of the period close process in Oracle Fusion General Ledger?",
        ["Close Subledgers → Reconcile Balances → Run Translation → Close General Ledger",
         "Run Translation → Close Subledgers → Reconcile Balances → Close General Ledger",
         "Reconcile Balances → Close Subledgers → Run Translation → Close General Ledger",
         "Close General Ledger → Reconcile Balances → Close Subledgers → Run Translation"], 0),
    mcq("What happens when an accounting period is permanently closed?",
        ["No changes can be made, and balances are finalized", "It can be reopened for adjustments if required",
         "Only manual journal entries can be posted", "Users can only view but not modify transactions"], 0),
    mcq("Which of the following must be enabled to use intercompany transactions in Oracle Fusion General Ledger?",
        ["Intercompany Balancing Rules", "Cross Validation Rules", "Subledger Accounting Rules", "Control Budget"], 0),
    mcq("In Oracle Fusion General Ledger, how are intercompany transactions settled?",
        ["Automatically through intercompany Receivables and Payables accounts", "By manually creating intercompany journal entries",
         "By manual reconciliation of intercompany balances", "Intercompany transactions do not require settlement as they are automatically reconciled"], 0),
    mcq("In Financial Reporting Studio, which component is used to define the data structure for reports?",
        ["Data Model", "Report Layout", "Chart of Accounts", "Report Designer"], 3),
    mcq("Which feature in Oracle Fusion General Ledger allows users to create ad-hoc financial reports using drag-and-drop functionality?",
        ["Account Analysis Report", "OTBI", "Financial Reporting Center", "Financial Data Quality Management"], 1),
    short("In a scenario where we need to restrict certain accounts to be used in AP and AR only and not in GL, how can we achieve this in Oracle Fusion General Ledger?"),
    short("How do related value sets work in the General Ledger module?"),
    short("What are the consequences of closing a General Ledger period while subledgers still have unposted transactions?"),
    short("If a journal is incorrectly posted in a previous open period, what are the best practices for correction?"),
    short("How can an organization restrict certain users from viewing financial data for specific primary balancing segment values while allowing them to access others?"),
    short("What are the two reversal methods used in Oracle Fusion?"),
    short("What is the report that shows all the unaccounted subledger transactions?"),
    short("What GL role is required to close the GL periods and add currency exchange rates in Fusion?"),
    short("Give two examples of recurring journals in Oracle Fusion."),
    short("What is the name of the dashboard that provides real-time visibility into the period close process from the subledgers to the General Ledger across the entire enterprise?"),
])

EPM = dict(name="Oracle EPM Planning - Interview Questions", duration_min=40, module="EPM - Planning", questions=[
    mcq("Which of the following modules is NOT a part of Oracle Fusion EPM Cloud?", ["Financial", "Workforce", "Procurement", "Projects"], 2),
    mcq("What is the purpose of Oracle Smart View?", ["Data visualization tool", "Spreadsheet-based analysis tool", "Security management tool", "Workflow automation tool"], 1),
    mcq('What is a "Scenario" used for in Oracle EPM?', ["Creating financial reports", "Defining time periods", "Managing different versions of a plan", "Forecasting models"], 2),
    mcq("Which Oracle Fusion EPM module is used for creating financial reports with details and explanations?",
        ["Planning", "Enterprise Data Management", "Narrative Reporting", "Account Reconciliation"], 2),
    mcq('What is a "Data Map" in Oracle EPM?', ["A visual representation of financial reports", "A mapping between source and target data models",
                                                "A machine learning algorithm", "A mapping between EPM Planning and ERP modules"], 1),
    mcq("Which of the following is a key feature of Financial Planning in Oracle EPM Cloud?",
        ["General ledger transactions", "Procurement workflows", "Predictive analytics and forecasting", "Payroll processing"], 2),
    mcq("What is the primary purpose of salary planning in Workforce Planning?",
        ["Allocating resources for capital investment", "Estimating labor costs and compensation", "Managing supplier relationships", "Forecasting IT expenditures"], 1),
    mcq('In Oracle EPM Cloud, "Drill-Through" allows users to:',
        ["Export reports to Excel", "View transaction-level details from aggregated data", "Manage user security", "Run batch jobs"], 1),
    mcq("Which factor is critical for effective project cost planning?",
        ["Material costs and labor expenses", "Number of project sponsors", "Marketing campaign spend", "Office furniture inventory"], 0),
    mcq("What type of assets are typically included in Capital Planning?",
        ["IT infrastructure, machinery, and buildings", "Human resources", "Vendor agreements", "Software subscriptions"], 0),
    short("What is a dimension in Oracle Planning?"),
    short("In simple terms, explain budget, forecast and actuals in Oracle EPM."),
    short("What are the default predefined roles in Oracle Fusion EPM Cloud?"),
    short("What is an Infolet in Oracle EPM Cloud?"),
    short("What is a Member Formula in Oracle Planning?"),
    short('What does the "Spreading" functionality do in Oracle EPM Planning?'),
    short("What is a best practice for entering planning data efficiently in Oracle EPM Cloud?"),
    short("Which types of reports can be created in Oracle EPM Planning?"),
    short("What is the primary benefit of using Dashboards in Oracle EPM Planning for reporting?"),
    short("How can users leverage predictive analytics in Oracle EPM Planning?"),
])

# Temporary passwords; everyone is made to choose their own at first sign-in.
TEAM = [
    ("Jibin Madayil John", "jmadayil@novamodus.com", "admin", "HM-Jibin-7K4p!"),
    ("Anitha Reddy", "areddy@novamodus.com", "recruiter", "HM-Anitha-3Rw9!"),
    ("Alankrutha", "alankrutha@novamodus.com", "recruiter", "HM-Alankrutha-5Tz6!"),
]

DEMO_USERNAME = "demo.candidate"
DEMO_PASSWORD = "DemoTest2026"


def seed_extras(db: Session):
    if get_setting(db, FLAG) == "done":
        return
    erp = db.query(models.Department).filter_by(name="ERP-EPM").first()

    by_module = {}
    for spec in (PROJECTS, AR, GL, EPM):
        t = db.query(models.Test).filter(func.lower(models.Test.name) == spec["name"].lower()).first()
        if not t:
            t = models.Test(name=spec["name"], duration_min=spec["duration_min"], instructions=INSTRUCTIONS,
                            department_id=erp.id if erp else None)
            t.questions = [models.Question(sort=i, **q) for i, q in enumerate(spec["questions"])]
            db.add(t)
            db.flush()
        by_module[spec["module"].lower()] = t
        mod = db.query(models.Module).filter(func.lower(models.Module.name) == spec["module"].lower()).first()
        if mod and not mod.test_id:
            mod.test_id = t.id

    for name, email, role, pw in TEAM:
        if not db.query(models.User).filter_by(email=email).first():
            db.add(models.User(name=name, email=email, role=role, password_hash=hash_password(pw), must_change_password=True))

    if not db.query(models.TestAssignment).filter_by(username=DEMO_USERNAME).first():
        stage = db.query(models.Stage).filter_by(name="Department Review").first()
        gl_mod = db.query(models.Module).filter(func.lower(models.Module.name) == "erp - general ledger").first()
        c = models.Candidate(first_name="Demo", last_name="Candidate", email="demo.candidate@example.com",
                             source="HireModus demo", notes="Practice record for trying the test portal. Safe to delete.",
                             stage_id=stage.id if stage else None, department_id=erp.id if erp else None,
                             module_id=gl_mod.id if gl_mod else None, custom={})
        db.add(c)
        db.flush()
        db.add(models.TestAssignment(candidate_id=c.id, test_id=by_module["erp - general ledger"].id,
                                     username=DEMO_USERNAME, password_hash=hash_password(DEMO_PASSWORD)))
    set_setting(db, FLAG, "done")
    db.commit()


# ---------------------------------------------------------------- v2: roles, aging, old AMS contact removal

FLAG2 = "seed_extras_v2"
REMOVED_EMAIL = "stomar@novamodus.com"
TEXT_FIXES = [
    ("Please feel free to reach out to me or Sidhant Singh Tomar if you have any questions or concerns.",
     "Please feel free to reach out to me if you have any questions or concerns."),
    ("please reach out to stomar@novamodus.com or hpatel@novamodus.com.",
     "please reach out to alankrutha@novamodus.com or hpatel@novamodus.com."),
]
AGING_TEMPLATE = dict(
    key="aging_alert", name="Aging alert (to recruiters)", include_global_cc=False, exclude_sender_from_cc=False,
    subject="{{count}} candidate(s) in {{area}} with no contact for {{alert_days}}+ days",
    body="""Hi,

These candidates in {{area}} haven't received any communication for {{alert_days}} days or more. Candidates who reach {{reject_days}} days without contact are rejected automatically.

{{candidate_list}}

Open HireModus to email them, book an interview, mark them as contacted, or mark them Keep.

Thank you""")
AGING_STAGES = {"AI Interview Pending", "AI Interview Sent", "Screening", "Department Review"}
TEAM_ROLES = {"jmadayil@novamodus.com": ["admin", "recruiter"], "areddy@novamodus.com": ["admin", "recruiter"],
              "alankrutha@novamodus.com": ["recruiter"]}


def _scrub_emails(text: str) -> str:
    from .services import split_emails, join_emails
    if not text or REMOVED_EMAIL not in text.lower():
        return text
    return join_emails([e for e in split_emails(text) if e != REMOVED_EMAIL])


def seed_v2(db: Session):
    from .perms import BUILTIN_ROLES
    from .aging import cfg as aging_cfg, initial_clock
    from .services import local_now
    if get_setting(db, FLAG2) == "done":
        return
    roles = {}
    for spec in BUILTIN_ROLES:
        r = db.query(models.Role).filter_by(key=spec["key"]).first()
        if not r:
            r = models.Role(**spec)
            db.add(r)
        roles[spec["key"]] = r
    db.flush()

    # users: old single role -> roles, team setup, remove the old AMS contact
    for u in db.query(models.User).all():
        if u.email == REMOVED_EMAIL:
            db.delete(u)
            continue
        if u.email in TEAM_ROLES:
            u.roles = [roles[k] for k in TEAM_ROLES[u.email]]
        elif not u.roles:
            u.roles = [roles.get(u.role) or roles["recruiter"]]
            if u.role == "admin":
                u.roles = [roles["admin"], roles["recruiter"]]

    # old AMS contact out of every list and text
    for key in ("global_cc", "it_emails", "it_cc", "aging_recipients"):
        set_setting(db, key, _scrub_emails(get_setting(db, key)))
    for d in db.query(models.Department):
        d.cc_emails = _scrub_emails(d.cc_emails)
    for t in db.query(models.EmailTemplate):
        t.cc = _scrub_emails(t.cc)
        for a, b in TEXT_FIXES:
            t.body = t.body.replace(a, b)
    for t in db.query(models.InterviewTemplate):
        for f in ("required_emails", "optional_emails", "flex_emails", "flex_preferred_emails"):
            setattr(t, f, _scrub_emails(getattr(t, f)))
        for a, b in TEXT_FIXES:
            t.invite_body = t.invite_body.replace(a, b)

    if not db.query(models.EmailTemplate).filter_by(key="aging_alert").first():
        db.add(models.EmailTemplate(**AGING_TEMPLATE))
    for st in db.query(models.Stage):
        if st.name in AGING_STAGES and st.kind == "open":
            st.aging_enabled = True

    # start aging clocks for candidates that don't have one, from their own dates
    conf = aging_cfg(db)
    now_local = local_now()
    past_iv = {}
    for iv in db.query(models.Interview).filter(models.Interview.status.in_(("scheduled", "sending"))):
        past_iv.setdefault(iv.candidate_id, []).append(iv.start)
    for c in db.query(models.Candidate).filter(models.Candidate.clock_started_at.is_(None)):
        dates = list(past_iv.get(c.id, []))
        if c.date_added:
            dates.append(datetime.combine(c.date_added, datetime.min.time()))
        if not dates:
            from .aging import to_local
            dates.append(to_local(c.created_at))
        initial_clock(c, dates, conf, now_local)
    set_setting(db, FLAG2, "done")
    db.commit()



# ---------------------------------------------------------------- v3: departments-only recruiters, associates, test departments

FLAG3 = "seed_extras_v3"


def seed_v3(db: Session):
    from .perms import BUILTIN_ROLES
    if get_setting(db, FLAG3) == "done":
        return
    specs = {r["key"]: r for r in BUILTIN_ROLES}
    roles = {}
    for key in ("admin", "recruiter", "associate"):
        r = db.query(models.Role).filter_by(key=key).first()
        if not r:
            r = models.Role(**specs[key])
            db.add(r)
        else:
            r.permissions = list(specs[key]["permissions"])
            r.department_scoped = specs[key].get("department_scoped", False)
            r.description = specs[key]["description"]
            r.builtin = True
        roles[key] = r
    db.flush()
    old = db.query(models.Role).filter_by(key="interviewer").first()
    if old:
        for u in db.query(models.User).all():
            if old in u.roles:
                u.roles = [x for x in u.roles if x.id != old.id] + ([roles["recruiter"]] if roles["recruiter"] not in u.roles else [])
        db.flush()
        db.delete(old)
    # tests belong to departments; a shared test belongs to every department whose interview type uses it
    depts = {d.name: d.id for d in db.query(models.Department)}
    for t in db.query(models.Test):
        ids = set(t.department_ids or [])
        if t.department_id:
            ids.add(t.department_id)
        for it in db.query(models.InterviewTemplate).filter_by(test_id=t.id):
            if it.department_id:
                ids.add(it.department_id)
        t.department_ids = sorted(ids)
        if ids and not t.department_id:
            t.department_id = sorted(ids)[0]
    set_setting(db, "recording_quality", get_setting(db, "recording_quality") or "high")
    set_setting(db, FLAG3, "done")
    db.commit()


# ---------------------------------------------------------------- v4: interview feedback form
FLAG4 = "seed_v4_done"


def seed_v4(db: Session):
    if get_setting(db, FLAG4) == "done":
        return
    if not db.query(models.FeedbackQuestion).count():
        for i, (label, kind, options, required) in enumerate([
            ("Overall rating", "rating", ["1", "2", "3", "4", "5"], True),
            ("Recommendation", "choice", ["Hire", "Maybe", "No hire"], True),
            ("Strengths", "text", [], False),
            ("Concerns", "text", [], False),
            ("Notes", "text", [], False),
        ]):
            db.add(models.FeedbackQuestion(label=label, kind=kind, options=options, required=required, sort=i))
    set_setting(db, FLAG4, "done")
    db.commit()
