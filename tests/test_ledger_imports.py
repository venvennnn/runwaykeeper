from datetime import UTC, datetime

from app.ledger import LedgerError, allocated_from_payment, create_allocation, invoice_outstanding
from app.models import Invoice, Payment, Workspace
from app.seed import uid
from tests.conftest import auth


def test_duplicate_import_is_idempotent(client):
    csv = """id,display_name,email,email_verified,contact_permission,timezone,source_id,source_ts
c-dup,Dup Co,dup@test.example,true,true,America/New_York,c-dup,2026-09-01T00:00:00+00:00
"""
    files = {"file": ("customers.csv", csv, "text/csv")}
    first = client.post("/api/imports/customers", data={"commit": "true"}, files=files, headers=auth())
    assert first.status_code == 200
    second = client.post("/api/imports/customers", data={"commit": "true"}, files=files, headers=auth())
    print("SECOND RESPONSE:", second.status_code, second.text)
    assert second.status_code == 200
    assert second.json()["skipped_duplicates"] >= 1
    assert second.json()["committed_rows"] == 0


def test_import_row_errors_before_commit(client):
    csv = """id,customer_id,issue_date,due_date,currency,gross_amount,external_reference,source_id,source_ts
bad,missing,not-a-date,2026-09-01,EUR,-12,INV-X,bad,nope
"""
    files = {"file": ("invoices.csv", csv, "text/csv")}
    res = client.post("/api/imports/invoices", data={"commit": "true"}, files=files, headers=auth())
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "invalid"
    assert body["errors"]
    assert body["committed_rows"] == 0


def test_over_allocation_and_cross_currency_rejected(db):
    workspace = db.get(Workspace, "00000000-0000-4000-8000-000000000001")
    invoice = db.get(Invoice, uid("invoice.inv-1108"))
    payment = Payment(
        id="pay-cross",
        workspace_id=workspace.id,
        customer_id=invoice.customer_id,
        amount_minor=50_000,
        currency="EUR",
        reference="INV-1108",
        settled_at=datetime(2026, 9, 10, tzinfo=UTC),
        source_id="pay-cross",
        source_ts=datetime(2026, 9, 10, tzinfo=UTC),
        ingested_at=datetime(2026, 9, 10, tzinfo=UTC),
        provenance="user_entered",
    )
    db.add(payment)
    db.flush()
    try:
        create_allocation(
            db,
            workspace,
            payment=payment,
            invoice=invoice,
            amount_minor=1,
            evidence={},
            source_id="x",
            source_ts=datetime(2026, 9, 10, tzinfo=UTC),
            provenance="user_entered",
        )
        assert False, "expected cross-currency rejection"
    except Exception:
        db.rollback()
        workspace = db.get(Workspace, "00000000-0000-4000-8000-000000000001")
        invoice = db.get(Invoice, uid("invoice.inv-1108"))

    payment = Payment(
        id="pay-over",
        workspace_id=workspace.id,
        customer_id=invoice.customer_id,
        amount_minor=10_000,
        currency="USD",
        reference="INV-1108",
        settled_at=datetime(2026, 9, 10, tzinfo=UTC),
        source_id="pay-over",
        source_ts=datetime(2026, 9, 10, tzinfo=UTC),
        ingested_at=datetime(2026, 9, 10, tzinfo=UTC),
        provenance="user_entered",
    )
    db.add(payment)
    db.flush()
    create_allocation(
        db,
        workspace,
        payment=payment,
        invoice=invoice,
        amount_minor=10_000,
        evidence={},
        source_id="ok-partial",
        source_ts=datetime(2026, 9, 10, tzinfo=UTC),
        provenance="user_entered",
    )
    try:
        create_allocation(
            db,
            workspace,
            payment=payment,
            invoice=invoice,
            amount_minor=1,
            evidence={},
            source_id="over",
            source_ts=datetime(2026, 9, 10, tzinfo=UTC),
            provenance="user_entered",
        )
        assert False
    except LedgerError:
        pass
    assert invoice_outstanding(db, invoice) > 0
    db.rollback()


def test_partial_payment_does_not_close_case(client, db):
    cases = client.get("/api/cases", headers=auth()).json()["cases"]
    fieldnote = next(c for c in cases if c["external_reference"] == "INV-1124")
    assert fieldnote["payment_status"] == "partial"
    assert fieldnote["collection_state"] != "closed"
    assert fieldnote["outstanding_minor"] == 210_000
