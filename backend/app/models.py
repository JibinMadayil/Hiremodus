from datetime import datetime, date
from sqlalchemy import (
    String, Integer, Boolean, DateTime, Date, Text, ForeignKey, JSON, Float, Table, Column,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow():
    return datetime.utcnow()


user_departments = Table(
    "user_departments",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("department_id", ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True),
)


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)  # admin | recruiter | custom_...
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    department_scoped: Mapped[bool] = mapped_column(Boolean, default=False)  # only sees own departments
    description: Mapped[str] = mapped_column(Text, default="")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="recruiter")  # admin | recruiter | interviewer
    password_hash: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    connector_key: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    connector_last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    connector_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    prefs: Mapped[dict] = mapped_column(JSON, default=dict)  # saved views, dashboard tiles
    mail_transport: Mapped[str] = mapped_column(String(20), default="default")  # default | connector | graph
    entra_oid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # Microsoft account id after first sign-in
    reply_scan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # connector inbox checked up to (UTC)
    graph_scan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Graph inbox checked up to (UTC)
    departments = relationship("Department", secondary=user_departments, lazy="selectin")
    roles = relationship("Role", secondary=user_roles, lazy="selectin")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    cc_emails: Mapped[str] = mapped_column(Text, default="")  # CC'd on rejection / withdrawal emails
    color: Mapped[str] = mapped_column(String(20), default="#4f6bed")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    cc: Mapped[str] = mapped_column(Text, default="")
    include_global_cc: Mapped[bool] = mapped_column(Boolean, default=True)
    include_department_cc: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_sender_from_cc: Mapped[bool] = mapped_column(Boolean, default=True)
    show_as_action: Mapped[bool] = mapped_column(Boolean, default=False)  # button on candidate page
    department_ids: Mapped[list] = mapped_column(JSON, default=list)  # empty = all departments
    moves_to_stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id", ondelete="SET NULL"), nullable=True)
    due_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # sets {{due_date}}
    notify_it: Mapped[bool] = mapped_column(Boolean, default=False)
    it_links: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Stage(Base):
    __tablename__ = "stages"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20), default="open")  # open | hired | rejected | withdrawn
    sort: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[str] = mapped_column(String(20), default="#64748b")
    entry_template_id: Mapped[int | None] = mapped_column(ForeignKey("email_templates.id", ondelete="SET NULL"), nullable=True)
    requires_department: Mapped[bool] = mapped_column(Boolean, default=False)
    advance_on_ai_link_to_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aging_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # counts toward the 30/45-day rules
    alert_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # override of the global setting
    reject_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Module(Base):
    __tablename__ = "modules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    web_link: Mapped[str] = mapped_column(Text, default="")
    training_link: Mapped[str] = mapped_column(Text, default="")
    test_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # test used when this module is picked
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Holiday(Base):
    __tablename__ = "holidays"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")


class InterviewTemplate(Base):
    __tablename__ = "interview_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    round_label: Mapped[str] = mapped_column(String(100), default="First Round")
    round_number: Mapped[int] = mapped_column(Integer, default=1)
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    weekdays: Mapped[list] = mapped_column(JSON, default=lambda: [1, 2, 3, 4, 5])  # 1=Mon .. 7=Sun
    day_start: Mapped[str] = mapped_column(String(5), default="09:00")
    day_end: Mapped[str] = mapped_column(String(5), default="18:00")
    search_offset_days: Mapped[int] = mapped_column(Integer, default=0)
    search_window_days: Mapped[int] = mapped_column(Integer, default=14)
    slot_options: Mapped[int] = mapped_column(Integer, default=5)
    check_own_calendar: Mapped[bool] = mapped_column(Boolean, default=True)
    location: Mapped[str] = mapped_column(Text, default="")
    required_emails: Mapped[str] = mapped_column(Text, default="")
    optional_emails: Mapped[str] = mapped_column(Text, default="")
    flex_emails: Mapped[str] = mapped_column(Text, default="")  # required if free, optional if busy
    flex_preferred_emails: Mapped[str] = mapped_column(Text, default="")  # first pass needs these free
    flex_min_free: Mapped[int] = mapped_column(Integer, default=1)
    ask_extra_cc: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_subject: Mapped[str] = mapped_column(String(500))
    invite_body: Mapped[str] = mapped_column(Text)
    send_confirmation_email: Mapped[bool] = mapped_column(Boolean, default=True)
    confirmation_subject: Mapped[str] = mapped_column(String(500), default="Interview Confirmation - {{company}}")
    requires_module: Mapped[bool] = mapped_column(Boolean, default=False)
    reuse_previous_module: Mapped[bool] = mapped_column(Boolean, default=False)
    includes_test: Mapped[bool] = mapped_column(Boolean, default=False)
    test_id: Mapped[int | None] = mapped_column(ForeignKey("tests.id", ondelete="SET NULL"), nullable=True)
    notify_it: Mapped[bool] = mapped_column(Boolean, default=False)
    it_links: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(120), default="")
    last_name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(320), default="", index=True)
    phone: Mapped[str] = mapped_column(String(60), default="")
    resume_link: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(120), default="")
    ai_interview_link: Mapped[str] = mapped_column(Text, default="")
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id", ondelete="SET NULL"), nullable=True)
    module_id: Mapped[int | None] = mapped_column(ForeignKey("modules.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # columns carried over from the Excel tracker
    location: Mapped[str] = mapped_column(String(200), default="")
    screening_result: Mapped[str] = mapped_column(Text, default="")
    screening_comments: Mapped[str] = mapped_column(Text, default="")
    oracle_experience: Mapped[str] = mapped_column(String(100), default="")
    area_fit: Mapped[str] = mapped_column(String(200), default="")
    ribbon_rating: Mapped[str] = mapped_column(String(40), default="")
    round1_info: Mapped[str] = mapped_column(Text, default="")
    round2_info: Mapped[str] = mapped_column(Text, default="")
    test_score: Mapped[str] = mapped_column(String(100), default="")
    interviewer: Mapped[str] = mapped_column(String(200), default="")
    interviewer_comment: Mapped[str] = mapped_column(Text, default="")
    practice: Mapped[str] = mapped_column(String(200), default="")
    final_decision: Mapped[str] = mapped_column(String(200), default="")
    date_added: Mapped[date | None] = mapped_column(Date, nullable=True)
    custom: Mapped[dict] = mapped_column(JSON, default=dict)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)  # values of admin-defined custom fields
    # aging: the clock restarts whenever the candidate is contacted
    clock_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # UTC
    last_contact_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aging_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    aging_grace_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    aging_alerted_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # clock value already alerted
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    stage_changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    retention_keep: Mapped[bool] = mapped_column(Boolean, default=False)  # an admin chose to keep this person's details
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # personal details cleared
    retention_warned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("interview_templates.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    round_number: Mapped[int] = mapped_column(Integer, default=1)
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    location: Mapped[str] = mapped_column(Text, default="")
    required: Mapped[str] = mapped_column(Text, default="")
    optional: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    module_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="sending")  # sending | scheduled | failed | cancelled
    outlook_entry_id: Mapped[str] = mapped_column(Text, default="")
    organizer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Test(Base):
    __tablename__ = "tests"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    department_ids: Mapped[list] = mapped_column(JSON, default=list)  # a test belongs to one or more departments
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    instructions: Mapped[str] = mapped_column(Text, default="")
    allow_file_upload: Mapped[bool] = mapped_column(Boolean, default=False)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, default=False)
    shuffle_options: Mapped[bool] = mapped_column(Boolean, default=False)
    pool_choice: Mapped[int | None] = mapped_column(Integer, nullable=True)  # draw this many choice questions
    pool_written: Mapped[int | None] = mapped_column(Integer, nullable=True)  # and this many written/file ones
    code_valid_minutes: Mapped[int] = mapped_column(Integer, default=30)
    record_camera: Mapped[bool] = mapped_column(Boolean, default=True)
    record_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    record_screen: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    questions = relationship("Question", order_by="Question.sort", cascade="all, delete-orphan", lazy="selectin")


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="mcq")  # mcq | multi | short | long | file
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)
    correct_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct_indices: Mapped[list] = mapped_column(JSON, default=list)  # for "multi": all must be picked, nothing else
    section: Mapped[str] = mapped_column(String(100), default="")
    image: Mapped[str] = mapped_column(Text, default="")  # picture shown with the question
    option_images: Mapped[list] = mapped_column(JSON, default=list)  # picture per option ("" = none)
    points: Mapped[float] = mapped_column(Float, default=1)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class TestAssignment(Base):
    __tablename__ = "test_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"))
    interview_id: Mapped[int | None] = mapped_column(ForeignKey("interviews.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    code_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    code_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    code_issued_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code_failures: Mapped[int] = mapped_column(Integer, default=0)
    login_failures: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="assigned")  # assigned | in_progress | submitted | graded | revoked
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    question_order: Mapped[list] = mapped_column(JSON, default=list)
    option_orders: Mapped[dict] = mapped_column(JSON, default=dict)  # {question_id: [original index, ...]} as shown
    events: Mapped[list] = mapped_column(JSON, default=list)
    auto_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewer_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Answer(Base):
    __tablename__ = "answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("test_assignments.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    value: Mapped[str] = mapped_column(Text, default="")
    file_name: Mapped[str] = mapped_column(String(300), default="")
    file_path: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Recording(Base):
    """One continuous camera or screen recording. A test can have several if the candidate had to re-share."""
    __tablename__ = "recordings"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("test_assignments.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # camera | screen
    mime: Mapped[str] = mapped_column(String(100), default="video/webm")
    path: Mapped[str] = mapped_column(Text, default="")
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)  # UTC
    last_chunk_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delete_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC instant of local midnight
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class OutboxJob(Base):
    __tablename__ = "outbox_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # send_mail | create_appointment | update_appointment | cancel_appointment | free_busy
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    interview_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued | claimed | done | failed | cancelled
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Transfer(Base):
    """A recruiter asking another department to take a candidate. Declining rejects the candidate."""
    __tablename__ = "transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    from_department_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_department_id: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending | accepted | declined | cancelled
    decided_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")


class Snapshot(Base):
    """Webcam still captured when the integrity checks flag something. Deleted with the recordings."""
    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("test_assignments.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(String(300), default="")
    path: Mapped[str] = mapped_column(Text, default="")
    delete_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class CustomField(Base):
    __tablename__ = "custom_fields"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    label: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="text")  # text | long | number | date | select | checkbox
    options: Mapped[list] = mapped_column(JSON, default=list)
    show_in_list: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # None = everyone with access
    permission: Mapped[str] = mapped_column(String(60), default="candidates.view")
    read_by: Mapped[list] = mapped_column(JSON, default=list)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_name: Mapped[str] = mapped_column(String(200), default="")
    candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text, default="")


class CandidateEmail(Base):
    """An email a candidate sent, picked up from a recruiter's or CC person's inbox. Stored once, however many inboxes had it."""
    __tablename__ = "candidate_emails"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str] = mapped_column(String(500), index=True)  # internet message id, used to store it once
    from_addr: Mapped[str] = mapped_column(String(320), default="")
    from_name: Mapped[str] = mapped_column(String(300), default="")
    to_addrs: Mapped[str] = mapped_column(Text, default="")
    cc_addrs: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    preview: Mapped[str] = mapped_column(String(400), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list] = mapped_column(JSON, default=list)  # [{name, size, file}]
    copies: Mapped[dict] = mapped_column(JSON, default=dict)  # {user_id: {"via": "connector"|"graph", "id": entry or message id}}
    read_by: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FeedbackQuestion(Base):
    """A question on the interview feedback form, editable in Settings."""
    __tablename__ = "feedback_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), default="text")  # rating | choice | text
    options: Mapped[list] = mapped_column(JSON, default=list)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Feedback(Base):
    """One interviewer's feedback on one interview."""
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)  # {question_id: value}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
