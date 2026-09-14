from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.cases import apply_state
from app.jobs import claim_jobs, complete_job, fail_job
from app.ledger import create_allocation, find_unambiguous_match, invoice_outstanding, payment_status
from app.models import Approval, CollectionCase, CollectionState, Invoice, Job, JobStatus, Payment, Workspace
from app.seed import uid
from tests.conftest import auth


def test_cannot_close_unpaid_from_promise(db):
    workspace = db.get(Workspace, "00000000-0000-4000-8000-000000000001")
    invoice = db.get(Invoice, uid("invoice.inv-1112"))
    case = db.query(CollectionCase).filter(CollectionCase.invoice_id == invoice.id).one()
    try:
        apply_state(db, workspace, case, CollectionState.CLOSED.value, reason="promise")
        assert False
    except ValueError as exc:
        assert "cannot close" in str(exc).lower()
    assert payment_status(db, invoice) != "paid"


def test_unambiguous_match_and_ambiguous_match(db):
    workspace = db.get(Workspace, "00000000-0000-4000-8000-000000000001")
    invoice = db.get(Invoice, uid("invoice.inv-1042"))
    payment, matched, reason = find_unambiguous_match(
        db,
        workspace,
        customer_id=invoice.customer_id,
        currency="USD",
        amount_minor=1_840_000,
        reference="INV-1042",
    )
    assert payment is not None
    assert matched is not None
    extra = Payment(
        id=str(uuid4()),
        workspace_id=workspace.id,
        customer_id=invoice.customer_id,
        amount_minor=1_840_000,
        currency="USD",
        reference="INV-1042",
        settled_at=datetime(2026, 8, 27, tzinfo=UTC),
        source_id="ambiguous-extra",
        source_ts=datetime(2026, 8, 27, tzinfo=UTC),
        ingested_at=datetime(2026, 8, 27, tzinfo=UTC),
        provenance="simulated",
    )
    db.add(extra)
    db.flush()
    payment2, matched2, reason2 = find_unambiguous_match(
        db,
        workspace,
        customer_id=invoice.customer_id,
        currency="USD",
        amount_minor=1_840_000,
        reference="INV-1042",
    )
    assert payment2 is None
    assert "ambiguous" in reason2
    db.rollback()


def test_stale_approval_rejected(client, db):
    workspace = db.get(Workspace, "00000000-0000-4000-8000-000000000001")
    invoice = db.get(Invoice, uid("invoice.inv-1108"))
    case = db.query(CollectionCase).filter(CollectionCase.invoice_id == invoice.id).one()
    approval = Approval(
        id=str(uuid4()),
        workspace_id=workspace.id,
        case_id=case.id,
        kind="disputed_balance",
        title="stale",
        summary="stale",
        proposed_payload={},
        evidence={},
        status="pending",
        case_version_at_creation=case.version,
        created_at=datetime.now(UTC),
    )
    db.add(approval)
    case.version += 1
    db.commit()
    res = client.post(f"/api/approvals/{approval.id}/decide", json={"approve": True}, headers=auth())
    assert res.status_code == 409


def test_worker_restart_resumes_from_db(db):
    workspace = db.get(Workspace, "00000000-0000-4000-8000-000000000001")
    job = Job(
        id=str(uuid4()),
        workspace_id=workspace.id,
        job_type="recompute_forecast",
        payload={},
        status=JobStatus.LEASED.value,
        unique_key=f"restart-{uuid4()}",
        run_after=datetime.now(UTC) - timedelta(seconds=1),
        lease_until=datetime.now(UTC) - timedelta(seconds=1),
        lease_owner="dead-worker",
        attempts=1,
        max_attempts=5,
    )
    db.add(job)
    db.commit()
    claimed = claim_jobs(db, "new-worker", limit=20)
    assert any(j.id == job.id for j in claimed)
    db.commit()


def test_payment_before_reminder_aborts_send(client, db):
    from app.email_adapter import capture_or_send
    from app.models import Message

    workspace = db.get(Workspace, "00000000-0000-4000-8000-000000000001")
    invoice = db.get(Invoice, uid("invoice.inv-1042"))
    case = db.query(CollectionCase).filter(CollectionCase.invoice_id == invoice.id).one()
    payment = db.query(Payment).filter(Payment.reference == "INV-1042").first()
    if invoice_outstanding(db, invoice) > 0:
        create_allocation(
            db,
            workspace,
            payment=payment,
            invoice=invoice,
            amount_minor=invoice_outstanding(db, invoice),
            evidence={"test": "paid-before-send"},
            source_id=f"test-alloc-{uuid4()}",
            source_ts=datetime.now(UTC),
            provenance="user_entered",
        )
        db.flush()
    try:
        capture_or_send(
            db,
            workspace,
            case=case,
            to_email=invoice.customer.email,
            subject="x",
            body="y",
            idempotency_key=f"test-paid-{uuid4()}",
            authorized_recipient=invoice.customer.email,
        )
        assert False, "should refuse send after payment"
    except ValueError:
        pass
    db.rollback()
