"""
Orchestrator Agent.

Controls the full article generation pipeline:
  1. SERP research  → checkpoint
  2. Outline creation → checkpoint
  3. Article writing → checkpoint
  4. Quality review → checkpoint
  5. Revision loop (if needed) → final result

Supports crash recovery via checkpoints.
"""

from __future__ import annotations

import time

from app.agents.outline_agent import generate_outline
from app.agents.serp_agent import analyze_serp
from app.agents.writer_agent import write_article
from app.core.config import settings
from app.core.exceptions import QualityThresholdError
from app.core.logging import get_logger
from app.models.schemas import (
    ArticleRequest,
    GeneratedArticle,
    Job,
    JobCheckpoint,
    JobStatus,
)
from app.services.job_store import job_store
from app.services.quality_scorer import score_article
from app.services.serp_service import SERPProvider, get_serp_provider

logger = get_logger(__name__)


async def run_pipeline(
    request: ArticleRequest,
    job: Job | None = None,
    serp_provider: SERPProvider | None = None,
) -> GeneratedArticle:
    """
    Execute the full SEO article generation pipeline.

    If a job with existing checkpoints is provided, the pipeline
    resumes from the last completed stage.
    """
    start_time = time.time()
    provider = serp_provider or get_serp_provider()

    # Create or reuse job
    if job is None:
        job = Job(request=request)
    job_store.save(job)

    checkpoint = job.checkpoint or JobCheckpoint()

    try:
        # ── Stage 1: SERP Research ────────────────────────────────────────
        if checkpoint.serp_analysis is None:
            job.advance_status(JobStatus.RESEARCHING)
            job_store.save(job)

            logger.info("[%s] Stage 1: SERP research for '%s'", job.id[:8], request.topic)
            checkpoint.serp_analysis = await analyze_serp(
                query=request.topic,
                serp_provider=provider,
            )
            job.checkpoint = checkpoint
            job_store.save(job)
            logger.info("[%s] Stage 1 complete — checkpointed", job.id[:8])
        else:
            logger.info("[%s] Stage 1: Resuming from checkpoint (SERP data exists)", job.id[:8])

        # ── Stage 2: Outline Generation ───────────────────────────────────
        if checkpoint.outline is None:
            job.advance_status(JobStatus.OUTLINING)
            job_store.save(job)

            logger.info("[%s] Stage 2: Generating outline", job.id[:8])
            checkpoint.outline = await generate_outline(
                serp_analysis=checkpoint.serp_analysis,
                target_word_count=request.target_word_count,
                language=request.language.value,
            )
            job.checkpoint = checkpoint
            job_store.save(job)
            logger.info("[%s] Stage 2 complete — checkpointed", job.id[:8])
        else:
            logger.info("[%s] Stage 2: Resuming from checkpoint (outline exists)", job.id[:8])

        # ── Stage 3: Article Writing ──────────────────────────────────────
        job.advance_status(JobStatus.WRITING)
        job_store.save(job)

        revision_feedback = None
        article: GeneratedArticle | None = None

        for revision_round in range(settings.max_revision_rounds + 1):
            if revision_round == 0 and checkpoint.draft_markdown:
                logger.info("[%s] Stage 3: Resuming from draft checkpoint", job.id[:8])
                # We have a draft but may need to rebuild the article object
                # Just continue to quality check

            logger.info(
                "[%s] Stage 3: Writing article (round %d/%d)",
                job.id[:8], revision_round + 1, settings.max_revision_rounds + 1,
            )
            article = await write_article(
                outline=checkpoint.outline,
                serp_analysis=checkpoint.serp_analysis,
                target_word_count=request.target_word_count,
                language=request.language.value,
                revision_feedback=revision_feedback,
            )

            checkpoint.draft_markdown = article.content_markdown
            job.checkpoint = checkpoint
            job_store.save(job)

            # ── Stage 4: Quality Review ───────────────────────────────────
            job.advance_status(JobStatus.REVIEWING)
            job_store.save(job)

            logger.info("[%s] Stage 4: Quality review (round %d)", job.id[:8], revision_round + 1)
            quality_report = score_article(article)
            article.quality_report = quality_report
            checkpoint.quality_report = quality_report
            job.checkpoint = checkpoint
            job_store.save(job)

            if quality_report.passed:
                logger.info(
                    "[%s] Quality PASSED (score=%.2f) on round %d",
                    job.id[:8], quality_report.overall_score, revision_round + 1,
                )
                break

            if revision_round < settings.max_revision_rounds:
                # ── Stage 5: Revision ─────────────────────────────────────
                job.advance_status(JobStatus.REVISING)
                job_store.save(job)

                revision_feedback = "The article needs improvements:\n" + "\n".join(
                    f"- {s}" for s in quality_report.revision_suggestions
                )
                logger.info(
                    "[%s] Quality FAILED (score=%.2f), triggering revision round %d. Issues: %s",
                    job.id[:8],
                    quality_report.overall_score,
                    revision_round + 2,
                    quality_report.revision_suggestions,
                )
            else:
                logger.warning(
                    "[%s] Quality below threshold after %d rounds (score=%.2f). Proceeding with best effort.",
                    job.id[:8],
                    settings.max_revision_rounds + 1,
                    quality_report.overall_score,
                )

        assert article is not None

        # ── Finalize ──────────────────────────────────────────────────────
        elapsed = time.time() - start_time
        article.generation_time_seconds = round(elapsed, 2)

        job.result = article
        job.advance_status(JobStatus.COMPLETED)
        job.attempts += 1
        job_store.save(job)

        logger.info(
            "[%s] Pipeline COMPLETED in %.1fs — %d words, quality=%.2f",
            job.id[:8], elapsed, article.word_count,
            article.quality_report.overall_score if article.quality_report else 0,
        )
        return article

    except Exception as exc:
        job.fail(str(exc))
        job.attempts += 1
        job_store.save(job)
        logger.error("[%s] Pipeline FAILED: %s", job.id[:8], exc)
        raise


async def resume_job(job_id: str) -> GeneratedArticle:
    """Resume a failed or interrupted job from its last checkpoint."""
    job = job_store.load(job_id)
    if job.status == JobStatus.COMPLETED:
        if job.result:
            return job.result
        raise ValueError(f"Job {job_id} is marked completed but has no result")

    if job.attempts >= job.max_attempts:
        raise QualityThresholdError(
            f"Job {job_id} has exceeded max attempts ({job.max_attempts})"
        )

    logger.info("Resuming job %s from status=%s", job_id, job.status.value)
    return await run_pipeline(request=job.request, job=job)
