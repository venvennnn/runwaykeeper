from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_workspace
from app.models import Workspace, WorkspaceMode
from app.seed import seed_workspace
from app.services.orchestration import run_workspace_agent

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.post("/reset")
def reset(db: Session = Depends(get_db), workspace: Workspace = Depends(get_workspace)):
    seed_workspace(db, reset=True)
    workspace = db.get(Workspace, workspace.id)
    return {"ok": True, "workspace_id": workspace.id, "mode": workspace.mode}


@router.post("/run-agent")
def run_agent(case_id: str | None = None, db: Session = Depends(get_db), workspace: Workspace = Depends(get_workspace)):
    result = run_workspace_agent(db, workspace, trigger="manual", case_id=case_id)
    db.commit()
    return result


@router.post("/mode")
def require_simulation(workspace: Workspace = Depends(get_workspace)):
    if workspace.mode != WorkspaceMode.SIMULATION.value:
        raise HTTPException(403, "simulation controls are separate from connected mode")
    return {"mode": workspace.mode}
