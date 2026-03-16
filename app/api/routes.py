"""
FastAPI REST API for the SEO Article Generation Service.

Endpoints:
  POST   /api/v1/articles/generate       — Start a new article generation job
  GET    /api/v1/jobs/{job_id}            — Get job status and result
  POST   /api/v1/jobs/{job_id}/resume     — Resume a failed/interrupted job
  GET    /api/v1/jobs                     — List all jobs (optional status filter)
  DELETE /api/v1/jobs/{job_id}            — Delete a job
  GET    /api/v1/health                   — Health check
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.agents.orchestrator import resume_job, run_pipeline
from app.core.exceptions import JobNotFoundError, QualityThresholdError
from app.models.schemas import (
    ArticleRequest,
    GeneratedArticle,
    Job,
    JobStatus,
)
from app.services.job_store import job_store

router = APIRouter(prefix="/api/v1")


# ─── Response models ─────────────────────────────────────────────────────────

from pydantic import BaseModel


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    id: str
    status: JobStatus
    created_at: str
    updated_at: str
    attempts: int
    error: Optional[str] = None
    result: Optional[GeneratedArticle] = None


class JobListResponse(BaseModel):
    jobs: list[JobStatusResponse]
    total: int


class HealthResponse(BaseModel):
    status: str
    version: str


# ─── Background task runner ──────────────────────────────────────────────────

def _run_pipeline_sync(request: ArticleRequest, job: Job):
    """Run the async pipeline in a new event loop (for background tasks)."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_pipeline(request, job))
    except Exception:
        pass  # Error is captured in job
    finally:
        loop.close()


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.post("/articles/generate", response_model=JobCreatedResponse, status_code=202)
async def generate_article(
    request: ArticleRequest,
    background_tasks: BackgroundTasks,
    sync: bool = Query(False, description="If true, run synchronously and return result"),
):
    """
    Start a new article generation job.

    By default, runs asynchronously and returns a job_id for polling.
    Use ?sync=true for synchronous execution (blocks until complete).
    """
    job = Job(request=request)
    job_store.save(job)

    if sync:
        try:
            result = await run_pipeline(request, job)
            return JobCreatedResponse(
                job_id=job.id,
                status="completed",
                message="Article generated successfully",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    background_tasks.add_task(_run_pipeline_sync, request, job)
    return JobCreatedResponse(
        job_id=job.id,
        status="pending",
        message="Job created. Poll GET /api/v1/jobs/{job_id} for status.",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    """Get the current status of a generation job."""
    try:
        job = job_store.load(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return JobStatusResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        attempts=job.attempts,
        error=job.error,
        result=job.result,
    )


@router.post("/jobs/{job_id}/resume", response_model=JobCreatedResponse)
async def resume_generation(
    job_id: str,
    background_tasks: BackgroundTasks,
    sync: bool = Query(False),
):
    """Resume a failed or interrupted job from its last checkpoint."""
    try:
        job = job_store.load(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status == JobStatus.COMPLETED:
        return JobCreatedResponse(
            job_id=job.id,
            status="completed",
            message="Job already completed.",
        )

    if sync:
        try:
            await resume_job(job_id)
            return JobCreatedResponse(
                job_id=job.id,
                status="completed",
                message="Job resumed and completed.",
            )
        except QualityThresholdError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    def _resume_sync():
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(resume_job(job_id))
        except Exception:
            pass
        finally:
            loop.close()

    background_tasks.add_task(_resume_sync)
    return JobCreatedResponse(
        job_id=job.id,
        status="resuming",
        message="Job resuming from checkpoint.",
    )


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    status: Optional[JobStatus] = Query(None, description="Filter by status"),
):
    """List all jobs, optionally filtered by status."""
    jobs = job_store.list_jobs(status=status)
    items = [
        JobStatusResponse(
            id=j.id,
            status=j.status,
            created_at=j.created_at.isoformat(),
            updated_at=j.updated_at.isoformat(),
            attempts=j.attempts,
            error=j.error,
            result=j.result if j.status == JobStatus.COMPLETED else None,
        )
        for j in jobs
    ]
    return JobListResponse(jobs=items, total=len(items))


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str):
    """Delete a job and its data."""
    try:
        job_store.load(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    job_store.delete(job_id)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="healthy", version="1.0.0")
