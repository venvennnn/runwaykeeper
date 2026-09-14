from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid5, NAMESPACE_DNS

from sqlalchemy.orm import Session

from app.audit import utcnow
from app.cases import ensure_case
from app.config import settings
from app.ledger import create_allocation
from app.models import (
    CashSnapshot,
    CollectionCase,
    CollectionState,
    Customer,
    Expense,
    Invoice,
    Payment,
    ProvenanceType,
    Workspace,
    WorkspaceMode,
)
from app.services.forecast_service import persist_forecast
from app.services.ranking import refresh_cases

AS_OF = datetime(2026, 9, 1, tzinfo=UTC)
SEED_NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def uid(name: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"runwaykeeper.{name}"))


def seed_workspace(db: Session, reset: bool = False) -> Workspace:
    if reset:
        _wipe(db, settings.demo_workspace_id)
    existing = db.get(Workspace, settings.demo_workspace_id)
    if existing and not reset:
        return existing
    workspace = existing or Workspace(
        id=settings.demo_workspace_id,
        name="Harbor Studio",
        base_currency="USD",
        mode=WorkspaceMode.SIMULATION.value,
        buffer_minor=3_000_000,
        reminder_cooldown_hours=72,
        max_reminders_per_case=3,
        auto_reminders_enabled=True,
        api_key=settings.demo_api_key,
    )
    if existing is None:
        db.add(workspace)
        db.flush()
    _customers(db, workspace)
    _historical_invoices(db, workspace)
    _live_invoices(db, workspace)
    _payments(db, workspace)
    _expenses(db, workspace)
    _cash(db, workspace)
    for invoice in db.query(Invoice).filter(Invoice.workspace_id == workspace.id):
        ensure_case(db, workspace, invoice)
    lumen_case = (
        db.query(CollectionCase)
        .filter(CollectionCase.invoice_id == uid("invoice.inv-1108"))
        .one_or_none()
    )
    if lumen_case:
        lumen_case.collection_state = CollectionState.MONITORING.value
    persist_forecast(db, workspace)
    refresh_cases(db, workspace)
    db.commit()
    return workspace


def _wipe(db: Session, workspace_id: str) -> None:
    from app.models import (
        Allocation,
        Approval,
        AuditEvent,
        ForecastRun,
        ImportBatch,
        Job,
        Message,
        Outbox,
    )

    for model in (
        Message,
        Approval,
        AuditEvent,
        ForecastRun,
        Job,
        Outbox,
        ImportBatch,
        CollectionCase,
        Allocation,
        Payment,
        Expense,
        Invoice,
        CashSnapshot,
        Customer,
    ):
        db.query(model).filter(model.workspace_id == workspace_id).delete()
    db.flush()


def _customers(db: Session, workspace: Workspace) -> None:
    rows = [
        ("northwind", "Northwind Media", "ap@northwind.test", True, True),
        ("lumen", "Lumen Partners", "accounts@lumen.test", True, True),
        ("brightlane", "Brightlane Health", "payables@brightlane.test", True, True),
        ("oakpine", "Oak & Pine", "hello@oakpine.test", False, False),
        ("fieldnote", "Fieldnote Co", "finance@fieldnote.test", True, True),
    ]
    for i in range(12):
        rows.append(
            (
                f"hist-{i:02d}",
                f"Archive Client {i:02d}",
                f"ap{i:02d}@archive.test",
                True,
                True,
            )
        )
    for key, name, email, verified, perm in rows:
        cid = uid(f"customer.{key}")
        if db.get(Customer, cid):
            continue
        db.add(
            Customer(
                id=cid,
                workspace_id=workspace.id,
                display_name=name,
                email=email,
                email_verified=verified,
                contact_permission=perm,
                timezone="America/New_York",
                source_id=f"cust-{key}",
                source_ts=AS_OF,
                ingested_at=AS_OF,
                provenance=ProvenanceType.SIMULATED.value,
            )
        )
    db.flush()


def _add_invoice(
    db: Session,
    workspace: Workspace,
    key: str,
    customer_key: str,
    ref: str,
    issue,
    due,
    amount: int,
) -> None:
    iid = uid(f"invoice.{key}")
    if db.get(Invoice, iid):
        return
    db.add(
        Invoice(
            id=iid,
            workspace_id=workspace.id,
            customer_id=uid(f"customer.{customer_key}"),
            issue_date=issue,
            due_date=due,
            currency="USD",
            gross_amount_minor=amount,
            external_reference=ref,
            source_id=ref,
            source_ts=AS_OF,
            ingested_at=AS_OF,
            provenance=ProvenanceType.SIMULATED.value,
        )
    )


def _historical_invoices(db: Session, workspace: Workspace) -> None:
    from datetime import date

    start = date(2025, 1, 6)
    for i in range(48):
        issue = start + timedelta(days=7 * i)
        due = issue + timedelta(days=21)
        amount = 80_000 + (i * 3_700)
        _add_invoice(
            db,
            workspace,
            f"hist-{i:02d}",
            f"hist-{i % 12:02d}",
            f"INV-H{i:03d}",
            issue,
            due,
            amount,
        )
    db.flush()


def _live_invoices(db: Session, workspace: Workspace) -> None:
    from datetime import date

    _add_invoice(db, workspace, "inv-1042", "northwind", "INV-1042", date(2026, 7, 21), date(2026, 8, 20), 1_840_000)
    _add_invoice(db, workspace, "inv-1108", "lumen", "INV-1108", date(2026, 7, 29), date(2026, 8, 28), 920_000)
    _add_invoice(db, workspace, "inv-1112", "brightlane", "INV-1112", date(2026, 8, 11), date(2026, 9, 10), 750_000)
    _add_invoice(db, workspace, "inv-1088", "oakpine", "INV-1088", date(2026, 8, 1), date(2026, 8, 31), 420_000)
    _add_invoice(db, workspace, "inv-1124", "fieldnote", "INV-1124", date(2026, 8, 20), date(2026, 9, 19), 310_000)
    db.flush()


def _payments(db: Session, workspace: Workspace) -> None:
    from datetime import date

    from app.models import Invoice as Inv

    for i in range(48):
        invoice = db.get(Inv, uid(f"invoice.hist-{i:02d}"))
        if invoice is None:
            continue
        settled = datetime.combine(invoice.due_date + timedelta(days=(i % 9) - 2), datetime.min.time(), tzinfo=UTC)
        pid = uid(f"payment.hist-{i:02d}")
        if db.get(Payment, pid):
            continue
        payment = Payment(
            id=pid,
            workspace_id=workspace.id,
            customer_id=invoice.customer_id,
            amount_minor=invoice.gross_amount_minor,
            currency="USD",
            reference=invoice.external_reference,
            settled_at=settled,
            source_id=f"pay-h{i:03d}",
            source_ts=settled,
            ingested_at=AS_OF,
            provenance=ProvenanceType.SIMULATED.value,
        )
        db.add(payment)
        db.flush()
        create_allocation(
            db,
            workspace,
            payment=payment,
            invoice=invoice,
            amount_minor=invoice.gross_amount_minor,
            evidence={"rule": "seed_historical_paid"},
            source_id=f"alloc-h{i:03d}",
            source_ts=settled,
            provenance=ProvenanceType.SIMULATED.value,
        )
    # Already-settled payment included in opening cash for INV-1042
    pid = uid("payment.inv-1042")
    if db.get(Payment, pid) is None:
        settled = datetime(2026, 8, 28, 16, 0, tzinfo=UTC)
        db.add(
            Payment(
                id=pid,
                workspace_id=workspace.id,
                customer_id=uid("customer.northwind"),
                amount_minor=1_840_000,
                currency="USD",
                reference="INV-1042",
                settled_at=settled,
                source_id="pay-inv-1042",
                source_ts=settled,
                ingested_at=AS_OF,
                provenance=ProvenanceType.SIMULATED.value,
            )
        )
    # Partial payment after opening for fieldnote — remaining balance only
    pid = uid("payment.inv-1124-partial")
    if db.get(Payment, pid) is None:
        settled = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
        payment = Payment(
            id=pid,
            workspace_id=workspace.id,
            customer_id=uid("customer.fieldnote"),
            amount_minor=100_000,
            currency="USD",
            reference="INV-1124",
            settled_at=settled,
            source_id="pay-inv-1124-partial",
            source_ts=settled,
            ingested_at=settled,
            provenance=ProvenanceType.SIMULATED.value,
        )
        db.add(payment)
        db.flush()
        invoice = db.get(Invoice, uid("invoice.inv-1124"))
        create_allocation(
            db,
            workspace,
            payment=payment,
            invoice=invoice,
            amount_minor=100_000,
            evidence={"rule": "seed_partial"},
            source_id="alloc-inv-1124-partial",
            source_ts=settled,
            provenance=ProvenanceType.SIMULATED.value,
        )
    db.flush()


def _expenses(db: Session, workspace: Workspace) -> None:
    from datetime import date

    rows = [
        ("payroll", "September payroll", 2_200_000, date(2026, 9, 15), True, None),
        ("rent", "Studio rent", 650_000, date(2026, 9, 28), True, None),
        ("software", "Design toolchain (estimated)", 89_000, date(2026, 9, 20), False, None),
        ("insurance", "Liability insurance — settled", 120_000, date(2026, 8, 15), True, datetime(2026, 8, 15, tzinfo=UTC)),
    ]
    for key, desc, amount, due, confirmed, settled in rows:
        eid = uid(f"expense.{key}")
        if db.get(Expense, eid):
            continue
        db.add(
            Expense(
                id=eid,
                workspace_id=workspace.id,
                description=desc,
                amount_minor=amount,
                due_date=due,
                confirmed=confirmed,
                settled_at=settled,
                source_id=f"exp-{key}",
                source_ts=AS_OF,
                ingested_at=AS_OF,
                provenance=ProvenanceType.SIMULATED.value,
            )
        )
    db.flush()


def _cash(db: Session, workspace: Workspace) -> None:
    sid = uid("cash.opening")
    if db.get(CashSnapshot, sid):
        return
    db.add(
        CashSnapshot(
            id=sid,
            workspace_id=workspace.id,
            balance_minor=3_825_000,
            effective_at=AS_OF,
            source="owner_entry",
            source_id="cash-opening",
            source_ts=AS_OF,
            ingested_at=AS_OF,
            provenance=ProvenanceType.USER_ENTERED.value,
        )
    )
    db.flush()
