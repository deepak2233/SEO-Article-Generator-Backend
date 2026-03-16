"""
File-based job persistence.

Uses JSON files under a configurable directory. Each job gets its own file.

Features:
  - Atomic writes (tmp → rename) to prevent corruption on crash
  - Path traversal prevention
  - Thread-safe single-process operation
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.exceptions import JobNotFoundError
from app.core.logging import get_logger
from app.models.schemas import Job, JobStatus

logger = get_logger(__name__)


class JobStore:
    """File-based job storage with atomic writes."""

    def __init__(self, store_dir: str | None = None) -> None:
        self._dir = Path(store_dir or settings.job_store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("JobStore initialized at %s", self._dir)

    def _validate_id(self, job_id: str) -> None:
        """Prevent path traversal attacks."""
        if not re.match(r"^[a-zA-Z0-9\-]+$", job_id):
            raise ValueError(f"Invalid job ID format: {job_id}")

    def _path(self, job_id: str) -> Path:
        self._validate_id(job_id)
        return self._dir / f"{job_id}.json"

    def save(self, job: Job) -> None:
        """Atomically persist a job to disk."""
        path = self._path(job.id)
        data = job.model_dump_json(indent=2)

        # Atomic write: write to temp file, then rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._dir),
            prefix=f".{job.id}_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
            os.replace(tmp_path, str(path))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.debug("Saved job %s (status=%s)", job.id, job.status.value)

    def load(self, job_id: str) -> Job:
        """Load a job from disk."""
        path = self._path(job_id)
        if not path.exists():
            raise JobNotFoundError(f"Job {job_id} not found")

        data = path.read_text()
        return Job.model_validate_json(data)

    def list_jobs(self, status: Optional[JobStatus] = None) -> list[Job]:
        """List all jobs, optionally filtered by status."""
        jobs = []
        for file_path in sorted(self._dir.glob("*.json")):
            try:
                job = Job.model_validate_json(file_path.read_text())
                if status is None or job.status == status:
                    jobs.append(job)
            except Exception as exc:
                logger.warning("Skipping corrupt job file %s: %s", file_path, exc)
        return jobs

    def delete(self, job_id: str) -> None:
        """Delete a job file."""
        path = self._path(job_id)
        if path.exists():
            path.unlink()
            logger.info("Deleted job %s", job_id)
        else:
            logger.warning("Attempted to delete non-existent job %s", job_id)


# ── Singleton instance ─────────────────────────────────────────────────────
job_store = JobStore()
