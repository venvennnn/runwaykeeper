from __future__ import annotations

import logging
import os
import time
from uuid import uuid4

from app.config import settings
from app.db import SessionLocal, init_db
from app.jobs import claim_jobs, complete_job, fail_job, process_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("runwaykeeper.worker")


def loop() -> None:
    init_db()
    worker_id = os.environ.get("WORKER_ID") or f"worker-{uuid4().hex[:8]}"
    logger.info("worker %s polling jobs", worker_id)
    while True:
        db = SessionLocal()
        try:
            jobs = claim_jobs(db, worker_id)
            db.commit()
            for job in jobs:
                try:
                    process_job(db, job)
                    complete_job(job)
                    db.commit()
                    logger.info("job %s %s succeeded", job.id, job.job_type)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    job = db.get(type(job), job.id)
                    fail_job(job, str(exc))
                    db.commit()
                    logger.exception("job %s failed: %s", job.id, exc)
        finally:
            db.close()
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    loop()
