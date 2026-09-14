from __future__ import annotations

from enum import Enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ProvenanceType(str, Enum):
    IMPORTED = "imported"
    USER_ENTERED = "user_entered"
    SIMULATED = "simulated"


class WorkspaceMode(str, Enum):
    SIMULATION = "simulation"
    CONNECTED = "connected"


class CollectionState(str, Enum):
    MONITORING = "monitoring"
    FOLLOWUP_DUE = "followup_due"
    AWAITING_REPLY = "awaiting_reply"
    PROMISED = "promised"
    DISPUTED = "disputed"
    NEEDS_REVIEW = "needs_review"
    CLOSED = "closed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class JobStatus(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryStatus(str, Enum):
    CAPTURED = "captured"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"


class RecordMixin:
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_ts: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default=WorkspaceMode.SIMULATION.value)
    buffer_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reminder_cooldown_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=72)
    max_reminders_per_case: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    auto_reminders_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    api_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    customers: Mapped[list["Customer"]] = relationship(back_populates="workspace")


class Customer(Base, RecordMixin):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("workspace_id", "source_id", name="uq_customers_workspace_source"),
        Index("ix_customers_workspace", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contact_permission: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/New_York")

    workspace: Mapped[Workspace] = relationship(back_populates="customers")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")


class Invoice(Base, RecordMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("workspace_id", "source_id", name="uq_invoices_workspace_source"),
        Index("ix_invoices_workspace", "workspace_id"),
        CheckConstraint("gross_amount_minor > 0", name="ck_invoice_positive"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(64), ForeignKey("customers.id"), nullable=False)
    issue_date: Mapped[object] = mapped_column(Date, nullable=False)
    due_date: Mapped[object] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    gross_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    external_reference: Mapped[str] = mapped_column(String(128), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="invoices")
    case: Mapped["CollectionCase | None"] = relationship(back_populates="invoice", uselist=False)


class Payment(Base, RecordMixin):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "source_id", name="uq_payments_workspace_source"),
        Index("ix_payments_workspace", "workspace_id"),
        CheckConstraint("amount_minor > 0", name="ck_payment_positive"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    customer_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("customers.id"), nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settled_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class Allocation(Base, RecordMixin):
    __tablename__ = "allocations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "source_id", name="uq_allocations_workspace_source"),
        UniqueConstraint("payment_id", "invoice_id", name="uq_allocation_payment_invoice"),
        CheckConstraint("allocated_amount_minor > 0", name="ck_allocation_positive"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    payment_id: Mapped[str] = mapped_column(String(64), ForeignKey("payments.id"), nullable=False)
    invoice_id: Mapped[str] = mapped_column(String(64), ForeignKey("invoices.id"), nullable=False)
    allocated_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    matching_evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default=ApprovalStatus.APPROVED.value)


class Expense(Base, RecordMixin):
    __tablename__ = "expenses"
    __table_args__ = (
        UniqueConstraint("workspace_id", "source_id", name="uq_expenses_workspace_source"),
        CheckConstraint("amount_minor > 0", name="ck_expense_positive"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[object] = mapped_column(Date, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settled_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CashSnapshot(Base, RecordMixin):
    __tablename__ = "cash_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)


class CollectionCase(Base, RecordMixin):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("workspace_id", "invoice_id", name="uq_case_invoice"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    invoice_id: Mapped[str] = mapped_column(String(64), ForeignKey("invoices.id"), nullable=False)
    collection_state: Mapped[str] = mapped_column(String(32), nullable=False, default=CollectionState.MONITORING.value)
    next_action_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    promise_date: Mapped[object | None] = mapped_column(Date, nullable=True)
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reminder_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cash_gap_sensitivity_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    invoice: Mapped[Invoice] = relationship(back_populates="case")


class Message(Base, RecordMixin):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    case_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("cases.id"), nullable=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="resend")
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    from_email: Mapped[str] = mapped_column(String(320), nullable=False)
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    delivery_status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_simulation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "unique_key", name="uq_jobs_unique_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.PENDING.value)
    unique_key: Mapped[str] = mapped_column(String(255), nullable=False)
    run_after: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (UniqueConstraint("workspace_id", "action_key", name="uq_outbox_action"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    action_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    case_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("cases.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ApprovalStatus.PENDING.value)
    case_version_at_creation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ForecastRun(Base):
    __tablename__ = "forecast_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    assumptions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_what_if: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    promise_case_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    case_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    committed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
