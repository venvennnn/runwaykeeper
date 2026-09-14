from __future__ import annotations

from pydantic import BaseModel, Field


class AgentDecision(BaseModel):
    action_type: str = Field(description="Concrete action taken or proposed")
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str
    proposed_state_transition: str | None = None
    case_id: str | None = None
    requires_owner: bool = False
