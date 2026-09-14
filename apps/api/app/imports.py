from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.ledger import LedgerError, create_allocation
from app.models import (
    Customer,
    Expense,
    ImportBatch,
    Invoice,
    Payment,
    ProvenanceType,
    Workspace,
)
from runwaykeeper_forecasting.money import MoneyError, parse_minor_amount

CUSTOMER_FIELDS = {
    "id",
    "display_name",
    "email",
    "email_verified",
    "contact_permission",
    "timezone",
    "source_id",
    "source_ts",
}
INVOICE_FIELDS = {
    "id",
    "customer_id",
    "issue_date",
    "due_date",
    "currency",
    "gross_amount",
    "external_reference",
    "source_id",
    "source_ts",
}
PAYMENT_FIELDS = {
    "id",
    "customer_id",
    "amount",
    "currency",
    "reference",
    "settled_at",
    "source_id",
    "source_ts",
}
EXPENSE_FIELDS = {
    "id",
    "description",
    "amount",
    "due_date",
    "confirmed",
    "settled_at",
    "source_id",
    "source_ts",
}


def _parse_bool(value: str, field: str, row_number: int) -> tuple[bool | None, str | None]:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True, None
    if normalized in {"0", "false", "no", "n"}:
        return False, None
    return None, f"row {row_number}: {field} must be true/false"


def _parse_date(value: str, field: str, row_number: int) -> tuple[date | None, str | None]:
    try:
        return date.fromisoformat(value.strip()[:10]), None
    except ValueError:
        return None, f"row {row_number}: {field} is not an ISO date"


def _parse_datetime(value: str, field: str, row_number: int) -> tuple[datetime | None, str | None]:
    raw = value.strip()
    if not raw:
        return None, f"row {row_number}: {field} is required"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, f"row {row_number}: {field} is not an ISO timestamp"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed, None


def _missing_fields(row: dict, required: set[str], row_number: int) -> list[str]:
    errors = []
    for field in required:
        if field not in row or row[field] is None or str(row[field]).strip() == "":
            if field == "customer_id" and required is PAYMENT_FIELDS:
                continue
            if field == "settled_at" and required is EXPENSE_FIELDS:
                continue
            errors.append(f"row {row_number}: missing {field}")
    return errors


def preview_and_commit(
    db: Session,
    workspace: Workspace,
    *,
    kind: str,
    filename: str,
    content: str,
    provenance: str,
    commit: bool,
) -> ImportBatch:
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise ValueError("CSV is missing a header row")
    fields = {name.strip() for name in reader.fieldnames}
    expected = {
        "customers": CUSTOMER_FIELDS,
        "invoices": INVOICE_FIELDS,
        "payments": PAYMENT_FIELDS,
        "expenses": EXPENSE_FIELDS,
    }[kind]
    errors: list[str] = []
    if not expected.issubset(fields) and not expected <= fields:
        missing = sorted(expected - fields)
        if missing:
            errors.append(f"schema missing columns: {', '.join(missing)}")
    rows = list(reader)
    seen_ids: set[str] = set()
    prepared: list[dict] = []
    for index, raw in enumerate(rows, start=2):
        row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
        errors.extend(_missing_fields(row, expected, index))
        source_id = row.get("id") or row.get("source_id")
        if source_id in seen_ids:
            errors.append(f"row {index}: duplicate ID {source_id}")
        seen_ids.add(source_id or f"missing-{index}")
        try:
            prepared.append(_prepare_row(kind, row, index, workspace, provenance))
        except ValueError as exc:
            errors.append(str(exc))
    batch = ImportBatch(
        id=str(uuid4()),
        workspace_id=workspace.id,
        kind=kind,
        filename=filename,
        status="preview" if not commit else "committed",
        errors=errors,
        committed_rows=0,
        skipped_duplicates=0,
    )
    if errors or not commit:
        if errors:
            batch.status = "invalid"
        db.add(batch)
        db.flush()
        return batch
    skipped = 0
    committed = 0
    for item in prepared:
        if _exists(db, workspace, kind, item["source_id"]):
            skipped += 1
            continue
        _insert(db, workspace, kind, item)
        committed += 1
    batch.committed_rows = committed
    batch.skipped_duplicates = skipped
    db.add(batch)
    db.flush()
    return batch


def _prepare_row(kind: str, row: dict, index: int, workspace: Workspace, provenance: str) -> dict:
    source_ts, err = _parse_datetime(row.get("source_ts", ""), "source_ts", index)
    if err:
        raise ValueError(err)
    source_id = row.get("source_id") or row["id"]
    base = {
        "id": row["id"],
        "source_id": source_id,
        "source_ts": source_ts,
        "ingested_at": datetime.now(UTC),
        "provenance": provenance,
    }
    if kind == "customers":
        verified, err = _parse_bool(row["email_verified"], "email_verified", index)
        perm, err2 = _parse_bool(row["contact_permission"], "contact_permission", index)
        if err or err2:
            raise ValueError(err or err2)
        return {
            **base,
            "display_name": row["display_name"],
            "email": row["email"],
            "email_verified": verified,
            "contact_permission": perm,
            "timezone": row.get("timezone") or "America/New_York",
        }
    if kind == "invoices":
        issue, err = _parse_date(row["issue_date"], "issue_date", index)
        due, err2 = _parse_date(row["due_date"], "due_date", index)
        if err or err2:
            raise ValueError(err or err2)
        try:
            amount = parse_minor_amount(row["gross_amount"], field="gross_amount")
        except MoneyError as exc:
            raise ValueError(f"row {index}: {exc}") from exc
        if amount <= 0:
            raise ValueError(f"row {index}: gross_amount must be positive")
        if row["currency"] != workspace.base_currency:
            raise ValueError(f"row {index}: currency {row['currency']} is not the workspace currency")
        return {
            **base,
            "customer_id": row["customer_id"],
            "issue_date": issue,
            "due_date": due,
            "currency": row["currency"],
            "gross_amount_minor": amount,
            "external_reference": row["external_reference"],
        }
    if kind == "payments":
        settled, err = _parse_datetime(row["settled_at"], "settled_at", index)
        if err:
            raise ValueError(err)
        try:
            amount = parse_minor_amount(row["amount"], field="amount")
        except MoneyError as exc:
            raise ValueError(f"row {index}: {exc}") from exc
        if amount <= 0:
            raise ValueError(f"row {index}: amount must be positive")
        if row["currency"] != workspace.base_currency:
            raise ValueError(f"row {index}: currency {row['currency']} is not the workspace currency")
        customer_id = row.get("customer_id") or None
        return {
            **base,
            "customer_id": customer_id,
            "amount_minor": amount,
            "currency": row["currency"],
            "reference": row.get("reference") or None,
            "settled_at": settled,
        }
    settled_at = None
    if row.get("settled_at"):
        settled_at, err = _parse_datetime(row["settled_at"], "settled_at", index)
        if err:
            raise ValueError(err)
    due, err = _parse_date(row["due_date"], "due_date", index)
    if err:
        raise ValueError(err)
    confirmed, err = _parse_bool(row["confirmed"], "confirmed", index)
    if err:
        raise ValueError(err)
    try:
        amount = parse_minor_amount(row["amount"], field="amount")
    except MoneyError as exc:
        raise ValueError(f"row {index}: {exc}") from exc
    return {
        **base,
        "description": row["description"],
        "amount_minor": amount,
        "due_date": due,
        "confirmed": confirmed,
        "settled_at": settled_at,
    }


def _exists(db: Session, workspace: Workspace, kind: str, source_id: str) -> bool:
    model = {"customers": Customer, "invoices": Invoice, "payments": Payment, "expenses": Expense}[kind]
    return (
        db.query(model)
        .filter(model.workspace_id == workspace.id, model.source_id == source_id)
        .first()
        is not None
    )


def _insert(db: Session, workspace: Workspace, kind: str, item: dict) -> None:
    if kind == "customers":
        db.add(
            Customer(
                id=item["id"],
                workspace_id=workspace.id,
                display_name=item["display_name"],
                email=item["email"],
                email_verified=item["email_verified"],
                contact_permission=item["contact_permission"],
                timezone=item["timezone"],
                source_id=item["source_id"],
                source_ts=item["source_ts"],
                ingested_at=item["ingested_at"],
                provenance=item["provenance"],
            )
        )
        return
    if kind == "invoices":
        customer = (
            db.query(Customer)
            .filter(Customer.workspace_id == workspace.id, Customer.id == item["customer_id"])
            .one_or_none()
        )
        if customer is None:
            raise ValueError(f"missing customer reference {item['customer_id']}")
        db.add(
            Invoice(
                id=item["id"],
                workspace_id=workspace.id,
                customer_id=item["customer_id"],
                issue_date=item["issue_date"],
                due_date=item["due_date"],
                currency=item["currency"],
                gross_amount_minor=item["gross_amount_minor"],
                external_reference=item["external_reference"],
                source_id=item["source_id"],
                source_ts=item["source_ts"],
                ingested_at=item["ingested_at"],
                provenance=item["provenance"],
            )
        )
        return
    if kind == "payments":
        if item["customer_id"]:
            customer = (
                db.query(Customer)
                .filter(Customer.workspace_id == workspace.id, Customer.id == item["customer_id"])
                .one_or_none()
            )
            if customer is None:
                raise ValueError(f"missing customer reference {item['customer_id']}")
        db.add(
            Payment(
                id=item["id"],
                workspace_id=workspace.id,
                customer_id=item["customer_id"],
                amount_minor=item["amount_minor"],
                currency=item["currency"],
                reference=item["reference"],
                settled_at=item["settled_at"],
                source_id=item["source_id"],
                source_ts=item["source_ts"],
                ingested_at=item["ingested_at"],
                provenance=item["provenance"],
            )
        )
        return
    db.add(
        Expense(
            id=item["id"],
            workspace_id=workspace.id,
            description=item["description"],
            amount_minor=item["amount_minor"],
            due_date=item["due_date"],
            confirmed=item["confirmed"],
            settled_at=item["settled_at"],
            source_id=item["source_id"],
            source_ts=item["source_ts"],
            ingested_at=item["ingested_at"],
            provenance=item["provenance"],
        )
    )


def maybe_auto_allocate_payment(db: Session, workspace: Workspace, payment: Payment) -> None:
    if not payment.reference or not payment.customer_id:
        return
    invoice = (
        db.query(Invoice)
        .filter(
            Invoice.workspace_id == workspace.id,
            Invoice.external_reference == payment.reference,
            Invoice.customer_id == payment.customer_id,
            Invoice.currency == payment.currency,
        )
        .one_or_none()
    )
    if invoice is None:
        return
    from app.ledger import invoice_outstanding

    outstanding = invoice_outstanding(db, invoice)
    amount = min(outstanding, payment.amount_minor)
    if amount <= 0:
        return
    try:
        create_allocation(
            db,
            workspace,
            payment=payment,
            invoice=invoice,
            amount_minor=amount,
            evidence={"rule": "unique_reference_customer_currency_amount"},
            source_id=f"auto:{payment.source_id}:{invoice.source_id}",
            source_ts=payment.source_ts,
            provenance=payment.provenance,
        )
    except (LedgerError, MoneyError):
        return
