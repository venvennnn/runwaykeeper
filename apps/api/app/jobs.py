from __future__ import annotations

import logging
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import utcnow
from app.config import settings
from app.models import Job, JobStatus, Workspace

logger = logging.getLogger(__name__)


def claim_jobs(db: Session, worker_id: str, limit: int = 5) -> list[Job]:
    now = utcnow()
    query = (
        select(Job)
        .where(
            Job.status.in_([JobStatus.PENDING.value, JobStatus.LEASED.value]),
            Job.run_after <= now,
            or_(Job.lease_until.is_(None), Job.lease_until < now),
            Job.attempts < Job.max_attempts,
        )
        .order_by(Job.created_at)
        .limit(limit)
    )
    if settings.database_url.startswith("postgresql"):
        query = query.with_for_update(skip_locked=True)
    jobs = list(db.scalars(query))
    lease_until = now + timedelta(seconds=settings.job_lease_seconds)
    for job in jobs:
        job.status = JobStatus.LEASED.value
        job.lease_until = lease_until
        job.lease_owner = worker_id
        job.attempts += 1
    db.flush()
    return jobs


def complete_job(job: Job) -> None:
    job.status = JobStatus.SUCCEEDED.value
    job.lease_until = None


def fail_job(job: Job, error: str) -> None:
    job.last_error = error[:4000]
    if job.attempts >= job.max_attempts:
        job.status = JobStatus.FAILED.value
        job.lease_until = None
    else:
        job.status = JobStatus.PENDING.value
        job.lease_until = utcnow() + timedelta(seconds=5 * job.attempts)
        job.run_after = job.lease_until


def process_job(db: Session, job: Job) -> None:
    workspace = db.get(Workspace, job.workspace_id)
    if workspace is None:
        raise RuntimeError("workspace missing for job")
    if job.job_type == "run_agent":
        from app.services.orchestration import run_workspace_agent

        run_workspace_agent(db, workspace, trigger=job.payload.get("trigger", "job"), case_id=job.payload.get("case_id"))
        return
    if job.job_type == "send_message":
        from app.email_adapter import dispatch_outbox_message

        dispatch_outbox_message(db, workspace, job.payload)
        return
    if job.job_type == "recompute_forecast":
        from app.services.forecast_service import persist_forecast

        persist_forecast(db, workspace)
        return
    raise RuntimeError(f"unknown job type {job.job_type}")
