"""First-run data for a new HireModus install.
Everything here is editable afterwards from Settings."""
import json
import os
from datetime import date

from sqlalchemy.orm import Session

from . import models
from .security import hash_password
from .services import set_setting, DEFAULT_SETTINGS

NM = "@novamodus.com"


def e(*names):
    return "; ".join(n + NM for n in names)


OFFICE_B10 = "2600 Skymark Avenue, Building 10, Suite 200, Mississauga, ON L4W 5B2"
OFFICE_B11 = "2600 Skymark Avenue, Building 11, Mississauga, ON L4W 5B2"
OFFICE_B01 = "2600 Skymark Avenue, Building 01, Suite 102, Mississauga, ON L4W 5B2"

R1_BODY = """Good Day {{first_name}},

I hope this message finds you well. We are pleased to invite you for an in-person interview for the position of Business Analyst - Oracle Applications at {{company}}.

By confirming your attendance, you are also acknowledging the following:

1. You are available to work onsite full-time at our office: 2600 Skymark Avenue, Mississauga.
2. You are open to travel up to 50%, depending on project requirements.
3. You are willing to complete an Oracle Fusion certification in your {{department}} focus

Interview Details
Date and Time: {{interview_date}} at {{interview_time}}
Location: {{location}}
{{resume_line}}

{{test_block}}

Please confirm your availability for this interview by replying to this email at your earliest convenience. If you have any questions or require additional information, feel free to reach out or raise them during the interview.

Thank you, and we look forward to meeting you in person.

Thank you"""

R2_BODY = """Good Day {{first_name}}
You have been shortlisted for the next steps, that are outlined below:

1. We are providing access to our Training Portal and other documents to enable you to get trained in Oracle Fusion Cloud Applications {{module}}. These are provided at no cost to you. {{module_training_link}}
   Additionally, you can also refer to Oracle Documents on {{module_web_link}}. We will conduct an internal in-person test (45 mins), followed by a brief presentation (10-15 minutes) and a Q&A session (15-20 minutes) on Oracle Fusion Cloud Applications- {{module}} module to ascertain your readiness to proceed for the next step in our hiring process.
Please note: You are expected to prepare and present on the module during the presentation segment of the interview.
2. If you clear this round of interview, we will provide you with an offer letter to join us within the next two weeks, subject to background checks.
3. Your offer letter will also indicate the following:
 - Your starting salary at the time of joining.
 - An automatic increase in your salary on your successful completion of your probation (six months from the date of joining), in addition to the one-time appreciation incentive mentioned in 5 i (b).
4. Please remember to bring your laptop with you.

5. Interview Date & Time: {{interview_date}} at {{interview_time}}

6. Instance Access: We are providing access to the Oracle Instance for you to familiarize with the Oracle Fusion Cloud Applications instance. {{instance_link}}

{{test_block}}

Please feel free to reach out to me if you have any questions or concerns. Looking forward to meeting you.

Thank you

Regards,
{{sender_name}}"""

AMS_R1_BODY = """Good day {{first_name}},

I hope this message finds you well.
We are pleased to invite you to an in-person interview for the position of Business Analyst - Oracle Applications at {{company}}.
By confirming your attendance, you acknowledge that:
 - You are available to work onsite full-time at our office located at 2600 Skymark Avenue, Mississauga.
 - You are open to travelling up to 50%, depending on project requirements.
 - You are willing to complete an Oracle Fusion certification.
Interview Details
Date and Time: {{interview_date}} at {{interview_time}}
Location: {{location}}
{{resume_line}}
Please confirm your availability by replying to this email at your earliest convenience. Should you have any questions or require additional information, please feel free to contact us or raise them during the interview.
Presentation Requirement
As part of the interview process, you will be required to prepare a 10-minute presentation on the following topic:
{{module}}
We are providing you with access to our Training Portal and supporting documents to help you become familiar with Oracle Fusion Cloud Applications:
Training Portal: {{module_training_link}}
Additional background information is available here:
Resource: {{module_web_link}}
You may access the Oracle instance credentials using the link below to familiarize yourself with the application:
{{instance_link}}
Interview Process
 - General Aptitude Test - 30 minutes
 - Presentation - 10 minutes
 - HR Interview - 20 minutes
Please bring your laptop with you for the assessment.

{{test_block}}

Thank you. We look forward to meeting you in person.

Regards,
{{sender_name}}"""

AMS_R2_BODY = """Good Day {{first_name}},

Thank you for attending your first round interview with us. We are pleased to invite you to the second round interview for the position of Business Analyst - Oracle Applications at {{company}}.

For this round, you will be building on the same topic you presented in your first round - Oracle Fusion Cloud Applications {{module}} - covering it in greater depth and demonstrating it live on the Oracle instance.

Interview format:
 - Presentation - 20 minutes: Please prepare a more detailed presentation on {{module}}, expanding on what you covered in your first round.
 - Demo - 40 minutes: You will walk us through a live demo of {{module}} using the Oracle Fusion Cloud Applications instance.

To help you prepare, please find below the Oracle Instance Credentials, which will give you access to the instance for your demo:
Oracle Instance Credentials: {{instance_link}}

You may also refer back to the materials shared with you earlier:
Training Portal: {{module_training_link}}
Oracle Documents: {{module_web_link}}

Interview Details
Date and Time: {{interview_date}} at {{interview_time}}
Location: {{location}}

Please bring your laptop with you, as it will be needed for the demo portion of the interview.

If you run into any access or login issues with the credentials or the instance, please reach out to alankrutha@novamodus.com or hpatel@novamodus.com.

Please confirm your availability for this interview by replying to this email at your earliest convenience. If you have any questions or require additional information, feel free to reach out or raise them during the interview.

Thank you, and we look forward to seeing your presentation and demo.

Regards,
{{sender_name}}"""

INTERN_BODY = """Good Day {{first_name}},

Greetings from {{company}}

Thank you for completing the AI interview. We would like to invite you to attend an in-person interview as the next step in the selection process.

Interview Details:
Date and Time: {{interview_date}} at {{interview_time}}
Location: {{location}}
{{resume_line}}

{{test_block}}

Please confirm your availability for the above schedule.

We look forward to meeting you."""

DEV_BODY = """Good Day {{first_name}},

I hope this message finds you well. We are pleased to invite you for an in-person interview for the position of Business Analyst - Oracle Applications at {{company}}.

By confirming your attendance, you are also acknowledging the following:

1. You are available to work onsite full-time at our office: 2600 Skymark Avenue, Mississauga.
2. You are open to travel up to 50%, depending on project requirements.
3. You are willing to complete an Oracle Fusion certification.

{{resume_line}}

For your interview next week, we would like you to prepare for a 10-minute presentation on Oracle Integration Cloud [OIC].
This will be followed by Technical and HR rounds.

Interview Details
Date and Time: {{interview_date}} at {{interview_time}}
Location: {{location}}

{{test_block}}

Please confirm your availability for this interview by replying to this email at your earliest convenience. If you have any questions or require additional information, feel free to reach out or raise them during the interview.

Thank you, and we look forward to meeting you in person.

Regards,
{{sender_name}}"""

EMAILS = [
    dict(key="ai_invite", name="AI interview invite", show_as_action=True,
         subject="Next Step: AI Interview - {{company}}",
         cc=e("areddy", "alankrutha"), include_global_cc=False,
         body="""Good Day {{first_name}},

Thank you for your interest in pursuing your career with Novamodus.

As part of the selection process, the first step is for you to take an interview using our AI agent. You can take the interview at any time convenient to you.

You can access the interview using the following link: {{ai_interview_link}}

Please ensure the following before you take the interview:
You have a computer or laptop with camera that is working.
Please ensure that your audio system is in good condition.
Please have your resume ready. You may be asked to upload it before you start the interview.
Please be alone in the room to avoid distractions and do not use the computer for any other purposes other than to attend the interview. The AI agent may assume that you are getting assistance from another person or that you are using your computer to search for answers.

Please feel free to reach out to me, through email, if you have any questions or if for some reason your interview runs into any issues.

Thank you"""),
    dict(key="rejection", name="Rejection", include_department_cc=True,
         subject="Update on your application to {{company}}",
         body="""Good Day {{first_name}},

Thank you for taking the time to apply to {{company}} and for the effort you put into your application/interview process.

After careful consideration, we regret to inform you that we will not be moving forward with your application at this time. The decision was difficult due to the high quality of candidates; however, we have decided to proceed with applicants whose experience more closely aligns with our current requirements.

We truly appreciate your interest in our organization and encourage you to apply for future opportunities that match your skills and experience. We wish you every success in your continued job search and professional journey.

Thank you again for your time and interest"""),
    dict(key="withdrawal", name="Withdrawal acknowledgment", include_department_cc=True,
         subject="Confirming your application withdrawal - {{company}}",
         body="""Good Day {{first_name}},

Thank you for letting us know that you have chosen to withdraw your application with {{company}}.

We appreciate the time and effort you put into your application, and we respect your decision. Your application has been closed accordingly, and no further action is needed on your part.

We hope you'll consider {{company}} again in the future, and we wish you all the best in your career search.

Thank you again for your time and interest"""),
    dict(key="phone_screening", name="Phone screening request", show_as_action=True, dept="Dev",
         subject="Next Step: Phone Screening - {{company}}", include_global_cc=False,
         cc=e("akumar", "gsubramanian", "lsaravanan", "areddy", "alankrutha"),
         body="""Good Day {{first_name}},

We are contacting you from Novamodus Solutions regarding the next step in the interview process.

As part of the first round, we would like to schedule a phone screening interview. Could you please share your availability for today or tomorrow with a suitable time slot?

Once we receive your availability, we will contact you during the confirmed time slot.

Looking forward to your response."""),
    dict(key="sql_assignment", name="SQL / BI Publisher assignment", show_as_action=True, dept="Dev", due_days=7,
         subject="Next Step: SQL/BI Publisher Assignment - {{company}}", include_global_cc=False,
         cc=e("akumar", "gsubramanian", "lsaravanan", "areddy", "alankrutha"),
         notify_it=True,
         it_links="BI Report Questions Document: https://novamodusinc.sharepoint.com/:w:/r/sites/Novamodus/Corporate/11.%20Leadership%20Team/05.%20Recruitment/Resumes/Dev%20Assessment/Novamodus%20Assignment%20-%20BI%20Report%20Questions.docx?d=w8e8ee71230cf49129f339a79d761bbd8&csf=1&web=1&e=Xlp68d\nOracle Instance Credentials (Demo): https://novamodusinc.sharepoint.com/:w:/s/NovamodusLearningPortal/IQBtIAOy5ARtQL5AIkXqeFMaAQ1KzKxuuhZO2siaQk8rC0E?e=g2gzlR",
         body="""Good Day {{first_name}},

Thank you for attending the interview with us. You have been selected to proceed to the next step in the hiring process.

We would like to test your SQL skills. Reference: https://www.w3schools.com/sql/

For your assignment, you are expected to create BI Publisher reports using SQL. Please use the link below for your assignment tasks.

The link to the Oracle Fusion demo instance is included in the Oracle Credentials file for you to practice. Please use Dev11 and work on the Reports assignment [SQL query]: https://novamodusinc.sharepoint.com/:w:/s/NovamodusLearningPortal/IQBtIAOy5ARtQL5AIkXqeFMaAQ1KzKxuuhZO2siaQk8rC0E?e=g2gzlR

When you login and access the BI Publisher area, under My Folders, create a sub folder with your own name so that your work is not lost. We do have our people using the same demo Oracle Fusion instance.

Please find the assignment tasks here: https://novamodusinc.sharepoint.com/:w:/r/sites/Novamodus/Corporate/11.%20Leadership%20Team/05.%20Recruitment/Resumes/Dev%20Assessment/Novamodus%20Assignment%20-%20BI%20Report%20Questions.docx?d=w8e8ee71230cf49129f339a79d761bbd8&csf=1&web=1&e=Xlp68d

You have 1 week to work on the assignment. We are hoping for you to submit your work on or before {{due_date}}.

Please feel free to reach out to us if you have any questions. All the best!

Thank you"""),
    dict(key="reschedule", name="Interview rescheduled", include_global_cc=False,
         subject="Interview Rescheduled - {{company}}",
         body="""Good Day {{first_name}},

Your interview has been rescheduled to {{interview_date}} at {{interview_time}}.

Please see the updated calendar invite for full details. If you have any questions, feel free to reach out.

Thank you"""),
    dict(key="test_access", name="Test login details", show_as_action=False, include_global_cc=False,
         subject="Your assessment login - {{company}}",
         body="""Good Day {{first_name}},

Here are your login details for the {{test_name}} assessment.

{{test_block}}

Thank you"""),
]

INSTANCE_LINK = "https://novamodusinc.sharepoint.com/:f:/r/sites/NovamodusLearningPortal/Shared%20Documents/Oracle%20Mylearn%20Videos/Oracle%20Instance%20Credentials?csf=1&web=1&e=6ilOvF"
R2_IT_LINKS = ("Training Portal: {{module_training_link}}\nOracle Documents: {{module_web_link}}\n"
               "Oracle Instance Credentials: {{instance_link}}")

DEPARTMENTS = [
    ("HCM", e("sahuja", "nudugama"), "#0ea5e9"),
    ("AMS", e("balla", "sdayanathan"), "#8b5cf6"),
    ("SCM", e("jahuja", "sgiri"), "#f59e0b"),
    ("ERP-EPM", e("mkaur", "nazia", "gpradeep", "parora", "sselvan"), "#10b981"),
    ("Dev", e("akumar", "gsubramanian", "lsaravanan"), "#ef4444"),
    ("Intern", e("areddy"), "#64748b"),
]

HOLIDAYS = [
    ("2026-01-01", "New Year's Day"), ("2026-02-16", "Family Day"), ("2026-04-03", "Good Friday"),
    ("2026-05-18", "Victoria Day"), ("2026-07-01", "Canada Day"), ("2026-09-07", "Labour Day"),
    ("2026-10-12", "Thanksgiving"), ("2026-12-25", "Christmas Day"), ("2026-12-26", "Boxing Day"),
    ("2027-01-01", "New Year's Day"), ("2027-02-15", "Family Day"), ("2027-03-26", "Good Friday"),
    ("2027-05-24", "Victoria Day"), ("2027-07-01", "Canada Day"), ("2027-09-06", "Labour Day"),
    ("2027-10-11", "Thanksgiving"), ("2027-12-25", "Christmas Day"), ("2027-12-26", "Boxing Day"),
]


def seed(db: Session):
    if db.query(models.User).count():
        return

    for k, v in DEFAULT_SETTINGS.items():
        set_setting(db, k, v)
    set_setting(db, "global_cc", e("areddy"))
    set_setting(db, "it_emails", e("skunnath", "hpatel"))
    set_setting(db, "it_cc", e("areddy", "alankrutha"))
    set_setting(db, "instance_credentials_link", INSTANCE_LINK)
    set_setting(db, "ai_interview_link", "https://app.ribbon.ai/interview/37171314")
    set_setting(db, "simulate_outlook", os.environ.get("HIREMODUS_SIMULATE_OUTLOOK", "true"))
    set_setting(db, "portal_base_url", os.environ.get("HIREMODUS_PORTAL_URL", "http://localhost:8000/portal"))

    db.add(models.User(
        name="HireModus Admin",
        email=os.environ.get("HIREMODUS_ADMIN_EMAIL", "admin@novamodus.com").lower(),
        role="admin",
        password_hash=hash_password(os.environ.get("HIREMODUS_ADMIN_PASSWORD", "ChangeMe123!")),
        must_change_password=True,
    ))

    depts = {}
    for i, (name, cc, color) in enumerate(DEPARTMENTS):
        d = models.Department(name=name, cc_emails=cc, color=color, sort=i)
        db.add(d)
        depts[name] = d
    db.flush()

    tpls = {}
    for t in EMAILS:
        t = dict(t)
        dept = t.pop("dept", None)
        tpl = models.EmailTemplate(**t, department_ids=[depts[dept].id] if dept else [])
        db.add(tpl)
        tpls[tpl.key] = tpl
    db.flush()

    stages = [
        dict(name="AI Interview Pending", color="#94a3b8"),
        dict(name="AI Interview Sent", color="#a78bfa"),
        dict(name="Screening", color="#38bdf8"),
        dict(name="Department Review", color="#f59e0b", requires_department=True),
        dict(name="Hired", kind="hired", color="#22c55e"),
        dict(name="Rejected", kind="rejected", color="#ef4444", entry_template_id=tpls["rejection"].id),
        dict(name="Withdrawn", kind="withdrawn", color="#78716c", entry_template_id=tpls["withdrawal"].id),
    ]
    st = []
    for i, s in enumerate(stages):
        obj = models.Stage(sort=i, **s)
        db.add(obj)
        st.append(obj)
    db.flush()
    st[1].advance_on_ai_link_to_id = st[2].id
    tpls["ai_invite"].moves_to_stage_id = st[1].id

    # the workbook's "Module Selection" sheet
    with open(os.path.join(os.path.dirname(__file__), "seed_modules.json"), encoding="utf-8") as fh:
        for m in json.load(fh):
            db.add(models.Module(**m))

    for d, n in HOLIDAYS:
        db.add(models.Holiday(day=date.fromisoformat(d), name=n))

    # sample tests, so the portal can be tried straight away
    apt = models.Test(name="General Aptitude Test", duration_min=30, department_id=depts["AMS"].id,
                      instructions="Answer every question. The timer starts when you press Start and the test submits itself when time runs out.")
    apt.questions = [
        models.Question(kind="mcq", sort=1, prompt="If 3 analysts complete 3 reports in 3 hours, how many reports do 6 analysts complete in 6 hours?",
                        options=["6", "9", "12", "18"], correct_index=2),
        models.Question(kind="mcq", sort=2, prompt="Which number comes next: 2, 6, 12, 20, 30, ?",
                        options=["38", "40", "42", "44"], correct_index=2),
        models.Question(kind="mcq", sort=3, prompt="A project budget of $80,000 is 25% spent. How much remains?",
                        options=["$20,000", "$55,000", "$60,000", "$64,000"], correct_index=2),
        models.Question(kind="short", sort=4, points=2, prompt="In two or three sentences, describe how you would explain a delayed go-live to a client."),
    ]
    mod = models.Test(name="Oracle Fusion Module Test", duration_min=45,
                      instructions="This test covers the module you prepared. Multiple choice is marked automatically; written answers are reviewed by the panel.")
    mod.questions = [
        models.Question(kind="mcq", sort=1, prompt="In Oracle Fusion General Ledger, which component defines the chart of accounts, calendar, currency and accounting method together?",
                        options=["Business unit", "Ledger", "Legal entity", "Data access set"], correct_index=1),
        models.Question(kind="mcq", sort=2, prompt="Which tool is used to load and configure setup data across Oracle Fusion instances?",
                        options=["Functional Setup Manager", "BI Publisher", "Smart View", "Transaction Console"], correct_index=0),
        models.Question(kind="long", sort=3, points=5, prompt="Walk through the main setup steps for the module you prepared and one common issue you would expect during testing."),
    ]
    dev = models.Test(name="Dev SQL / BI Publisher Test", duration_min=60, department_id=depts["Dev"].id,
                      allow_file_upload=True,
                      instructions="Write your SQL in the answer boxes. For the report question, upload a screenshot or the exported file.")
    dev.questions = [
        models.Question(kind="long", sort=1, points=5, prompt="Write a SQL query that returns each supplier and their total invoice amount for the current year, highest first."),
        models.Question(kind="mcq", sort=2, prompt="Which clause filters rows after aggregation?",
                        options=["WHERE", "HAVING", "GROUP BY", "ORDER BY"], correct_index=1),
        models.Question(kind="file", sort=3, points=5, prompt="Upload your BI Publisher report output (PDF, XLSX or a screenshot)."),
    ]
    db.add_all([apt, mod, dev])
    db.flush()

    def it(name, dept, rnd, label, dur, req, body, **kw):
        t = models.InterviewTemplate(
            name=name, department_id=depts[dept].id if dept else None, round_number=rnd, round_label=label,
            duration_min=dur, required_emails=req, invite_body=body, **kw)
        db.add(t)
        return t

    opt = e("areddy")
    for dept, req in [("HCM", e("sahuja", "nudugama")), ("SCM", e("jahuja", "sgiri"))]:
        it(f"{dept} - First Round", dept, 1, "First Round", 30, req, R1_BODY, optional_emails=opt,
           location=OFFICE_B10, invite_subject="First Round Interview - {{full_name}} - {{company}}",
           confirmation_subject="First Round Interview Confirmation - {{company}}")
        it(f"{dept} - Second Round", dept, 2, "Second Round", 60, req, R2_BODY, optional_emails=opt,
           location=OFFICE_B10, search_offset_days=14, requires_module=True, notify_it=True, it_links=R2_IT_LINKS,
           includes_test=True, test_id=mod.id,
           invite_subject="Second Round Interview - {{full_name}} - {{company}}",
           confirmation_subject="Second Round Interview Confirmation - {{company}}")

    erp = dict(required_emails=e("mkaur", "nazia"), flex_emails=e("gpradeep", "parora", "sselvan"),
               flex_preferred_emails=e("parora", "sselvan"), weekdays=[1, 5], optional_emails=opt, location=OFFICE_B10)
    t = models.InterviewTemplate(name="ERP-EPM - First Round", department_id=depts["ERP-EPM"].id, round_number=1,
                                 round_label="First Round", duration_min=30, invite_body=R1_BODY,
                                 invite_subject="First Round Interview - {{full_name}} - {{company}}",
                                 confirmation_subject="First Round Interview Confirmation - {{company}}", **erp)
    db.add(t)
    t = models.InterviewTemplate(name="ERP-EPM - Second Round", department_id=depts["ERP-EPM"].id, round_number=2,
                                 round_label="Second Round", duration_min=60, invite_body=R2_BODY, search_offset_days=14,
                                 requires_module=True, notify_it=True, it_links=R2_IT_LINKS, includes_test=True, test_id=mod.id,
                                 invite_subject="Second Round Interview - {{full_name}} - {{company}}",
                                 confirmation_subject="Second Round Interview Confirmation - {{company}}", **erp)
    db.add(t)

    ams = e("balla", "sdayanathan", "sjangala")
    it("AMS - First Round", "AMS", 1, "First Round", 60, ams, AMS_R1_BODY, optional_emails=opt, location=OFFICE_B11,
       day_start="16:00", day_end="18:00", search_offset_days=14, requires_module=True, notify_it=True,
       it_links=R2_IT_LINKS, includes_test=True, test_id=apt.id,
       invite_subject="Interview - {{full_name}} - {{company}}", confirmation_subject="Interview Confirmation - {{company}}")
    it("AMS - Second Round", "AMS", 2, "Second Round", 60, ams, AMS_R2_BODY, optional_emails=opt, location=OFFICE_B11,
       day_start="16:00", day_end="18:00", search_offset_days=14, requires_module=True, reuse_previous_module=True,
       notify_it=True, it_links=R2_IT_LINKS,
       invite_subject="Second Round Interview - {{full_name}} - {{company}}",
       confirmation_subject="Second Round Interview Confirmation - {{company}}")
    it("Intern - In-Person Interview", "Intern", 1, "In-Person Interview", 30, e("areddy"), INTERN_BODY,
       ask_extra_cc=True, location="2600 Skymark Ave, B10, Suite 200, Mississauga",
       invite_subject="In-Person Interview - {{full_name}} - {{company}}",
       confirmation_subject="Interview Confirmation - {{company}}")
    it("Dev - OIC + HR Round", "Dev", 1, "OIC + HR Round", 30, e("akumar", "gsubramanian", "lsaravanan"), DEV_BODY,
       optional_emails=e("areddy", "alankrutha"), search_offset_days=7, location=OFFICE_B01,
       invite_subject="In-Person Interview - {{full_name}} - {{company}}",
       confirmation_subject="Interview Confirmation - {{company}}")
    db.commit()
