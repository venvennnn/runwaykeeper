from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit import record_audit, utcnow
from app.db import get_db
from app.deps import get_workspace
from app.ledger import create_allocation
from app.models import (
    Approval,
    ApprovalStatus,
    CollectionCase,
    CollectionState,
    Invoice,
    Payment,
    ProvenanceType,
    Workspace,
)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class DecisionIn(BaseModel):
    approve: bool


@router.get("")
def list_approvals(db: Session = Depends(get_db), workspace: Workspace = Depends(get_workspace)):
    rows = (
        db.query(Approval)
        .filter(Approval.workspace_id == workspace.id)
        .order_by(Approval.created_at.desc())
        .all()
    )
    return {
        "approvals": [
            {
                "id": a.id,
                "kind": a.kind,
                "title": a.title,
                "summary": a.summary,
                "status": a.status,
                "proposed_payload": a.proposed_payload,
                "evidence": a.evidence,
                "case_id": a.case_id,
                "case_version_at_creation": a.case_version_at_creation,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ]
    }


@router.post("/{approval_id}/decide")
def decide(
    approval_id: str,
    body: DecisionIn,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_workspace),
):
    approval = (
        db.query(Approval)
        .filter(Approval.workspace_id == workspace.id, Approval.id == approval_id)
        .one_or_none()
    )
    if approval is None:
        raise HTTPException(404, "approval not found")
    if approval.status != ApprovalStatus.PENDING.value:
        raise HTTPException(400, "approval is not pending")
    if approval.case_id:
        case = db.get(CollectionCase, approval.case_id)
        if case and case.version != approval.case_version_at_creation:
            approval.status = ApprovalStatus.REJECTED.value
            approval.decided_at = utcnow()
            record_audit(
                db,
                workspace,
                event_type="stale_approval",
                entity_type="approval",
                entity_id=approval.id,
                payload={"case_version": case.version, "expected": approval.case_version_at_creation},
                case_version=case.version,
            )
            db.commit()
            raise HTTPException(409, "stale approval: case version changed")
    approval.status = ApprovalStatus.APPROVED.value if body.approve else ApprovalStatus.REJECTED.value
    approval.decided_at = utcnow()
    if body.approve and approval.kind == "allocation_conflict":
        payload = approval.proposed_payload
        payment = db.get(Payment, payload["payment_id"])
        invoice = db.get(Invoice, payload["invoice_id"])
        create_allocation(
            db,
            workspace,
            payment=payment,
            invoice=invoice,
            amount_minor=int(payload["amount_minor"]),
            evidence={"approval_id": approval.id},
            source_id=f"approval:{approval.id}",
            source_ts=utcnow(),
            provenance=ProvenanceType.USER_ENTERED.value,
        )
    if approval.case_id:
        case = db.get(CollectionCase, approval.case_id)
        if case and body.approve and approval.kind == "disputed_balance":
            case.collection_state = CollectionState.DISPUTED.value
            case.version += 1
        elif case and not body.approve and approval.kind == "disputed_balance":
            case.collection_state = CollectionState.FOLLOWUP_DUE.value
            case.dispute_reason = None
            case.version += 1
    record_audit(
        db,
        workspace,
        event_type="approval_decided",
        entity_type="approval",
        entity_id=approval.id,
        payload={"approve": body.approve, "kind": approval.kind},
    )
    db.commit()
    return {"id": approval.id, "status": approval.status}
