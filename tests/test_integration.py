"""
Integration tests — full pipeline with mocked LLM.

These tests verify the orchestration logic, checkpoint/resume,
and error handling without needing a real LLM API key.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.orchestrator import run_pipeline, resume_job
from app.core.exceptions import JobNotFoundError
from app.models.schemas import (
    ArticleRequest,
    Job,
    JobCheckpoint,
    JobStatus,
    Language,
    SERPAnalysis,
    SERPResult,
)
from app.services.job_store import JobStore
from app.services.serp_service import MockSERPProvider


def _make_serp_analysis_json(query="test"):
    return json.dumps({
        "query": query,
        "results": [],
        "common_themes": ["theme1", "theme2", "theme3", "theme4"],
        "common_subtopics": ["sub1", "sub2", "sub3", "sub4", "sub5"],
        "avg_title_length": 55.0,
        "common_title_patterns": ["N Best X"],
        "content_gaps": ["gap1", "gap2"],
        "faq_questions": ["What is X?", "How to Y?", "Why Z?"],
        "primary_keyword": "productivity tools for remote teams",
        "secondary_keywords": ["remote work", "team tools", "collaboration"],
    })


def _make_outline_json():
    return json.dumps({
        "title": "Best Productivity Tools for Remote Teams",
        "headings": [
            {"level": 1, "text": "Best Productivity Tools for Remote Teams", "target_word_count": 50, "keywords_to_include": [], "notes": ""},
            {"level": 2, "text": "Introduction", "target_word_count": 200, "keywords_to_include": ["productivity tools for remote teams"], "notes": ""},
            {"level": 2, "text": "Top Project Management Tools", "target_word_count": 300, "keywords_to_include": ["project management"], "notes": ""},
            {"level": 3, "text": "Asana", "target_word_count": 100, "keywords_to_include": [], "notes": ""},
            {"level": 3, "text": "Trello", "target_word_count": 100, "keywords_to_include": [], "notes": ""},
            {"level": 2, "text": "Communication Platforms", "target_word_count": 250, "keywords_to_include": ["team collaboration"], "notes": ""},
            {"level": 2, "text": "Time Tracking", "target_word_count": 200, "keywords_to_include": [], "notes": ""},
            {"level": 2, "text": "AI-Powered Productivity Tools", "target_word_count": 200, "keywords_to_include": [], "notes": ""},
            {"level": 2, "text": "FAQ", "target_word_count": 150, "keywords_to_include": [], "notes": ""},
            {"level": 2, "text": "Conclusion", "target_word_count": 100, "keywords_to_include": [], "notes": ""},
        ],
        "target_total_words": 1500,
        "search_intent": "commercial investigation",
        "tone": "informative, authoritative",
    })


def _make_article_markdown():
    """Generate a realistic 1500-word mock article."""
    sections = [
        "# Best Productivity Tools for Remote Teams",
        "",
        "## Introduction",
        "",
        "Finding the right productivity tools for remote teams can transform how your organization operates. "
        "In this guide, we cover the best solutions for distributed teams in 2025. "
        "Remote work demands specialized tools that bridge the gap between office and home. " * 5,
        "",
        "## Top Project Management Tools",
        "",
        "Project management is essential for remote teams to stay organized and meet deadlines. "
        "The right tool helps track progress and assign work effectively. " * 8,
        "",
        "### Asana",
        "",
        "Asana provides a flexible workspace with timeline views and automation. " * 5,
        "",
        "### Trello",
        "",
        "Trello uses kanban boards for visual task management. " * 5,
        "",
        "## Communication Platforms",
        "",
        "Effective team collaboration requires seamless communication tools. "
        "Slack, Teams, and Zoom each serve different needs for remote teams. " * 8,
        "",
        "## Time Tracking",
        "",
        "Time tracking helps remote teams maintain accountability. "
        "Tools like Toggl and Harvest offer detailed reports and integrations. " * 6,
        "",
        "## AI-Powered Productivity Tools",
        "",
        "AI is reshaping how remote teams work. "
        "Tools like Notion AI and Motion automate repetitive tasks. " * 6,
        "",
        "## FAQ",
        "",
        "### What is the best free productivity tool?",
        "",
        "Trello and Notion both offer generous free tiers suitable for small teams.",
        "",
        "### How do remote teams stay productive?",
        "",
        "By combining the right tools with clear processes and regular communication.",
        "",
        "## Conclusion",
        "",
        "Choosing the right productivity tools for remote teams requires understanding your needs. "
        "Start with communication, add project management, and scale from there. " * 3,
    ]
    return "\n".join(sections)


def _make_linking_json():
    return json.dumps({
        "internal_links": [
            {"anchor_text": "project management guide", "suggested_target_page": "/project-management", "context": "Introduction"},
            {"anchor_text": "remote work best practices", "suggested_target_page": "/remote-work", "context": "Communication"},
            {"anchor_text": "team building activities", "suggested_target_page": "/team-building", "context": "Conclusion"},
        ],
        "external_references": [
            {"title": "Buffer Remote Work Report", "url": "https://buffer.com/remote-work", "authority_reason": "Industry report", "placement_context": "Introduction"},
            {"title": "Harvard Business Review", "url": "https://hbr.org/remote-teams", "authority_reason": "Academic credibility", "placement_context": "Communication"},
        ],
    })


def _make_meta_json():
    return json.dumps({
        "title_tag": "Best Productivity Tools for Remote Teams 2025",
        "meta_description": "Discover the best productivity tools for remote teams in 2025. Compare project management, communication, and AI-powered solutions.",
        "primary_keyword": "productivity tools for remote teams",
        "secondary_keywords": ["remote work tools", "team collaboration", "project management"],
    })


@pytest.fixture
def mock_llm_responses():
    """Mock the LLM to return structured responses in sequence."""
    responses = [
        _make_serp_analysis_json("best productivity tools for remote teams"),
        _make_outline_json(),
        _make_article_markdown(),
        _make_linking_json(),
        _make_meta_json(),
    ]
    call_count = {"n": 0}

    async def mock_chat(*args, **kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(responses):
            return responses[idx]
        return responses[-1]

    return mock_chat


@pytest.mark.asyncio
class TestFullPipeline:
    @patch("app.agents.serp_agent.structured_completion")
    @patch("app.agents.outline_agent.structured_completion")
    @patch("app.agents.writer_agent.chat_completion")
    @patch("app.agents.writer_agent.structured_completion")
    async def test_pipeline_completes(
        self, mock_writer_struct, mock_writer_chat, mock_outline, mock_serp
    ):
        """Full pipeline should complete with mocked LLM."""
        from app.models.schemas import SERPAnalysis, ArticleOutline

        mock_serp.return_value = SERPAnalysis.model_validate_json(_make_serp_analysis_json())
        mock_outline.return_value = ArticleOutline.model_validate_json(_make_outline_json())
        mock_writer_chat.return_value = _make_article_markdown()

        # structured_completion is called twice per round (linking + meta)
        # Quality may trigger revision rounds, so provide enough for 3 rounds
        from app.agents.writer_agent import _LinkingOutput, _MetaOutput
        linking = _LinkingOutput.model_validate_json(_make_linking_json())
        meta = _MetaOutput.model_validate_json(_make_meta_json())
        mock_writer_struct.side_effect = [linking, meta] * 3

        request = ArticleRequest(topic="best productivity tools for remote teams")
        provider = MockSERPProvider()
        result = await run_pipeline(request, serp_provider=provider)

        assert result.title
        assert result.content_markdown
        assert result.seo_metadata.primary_keyword
        assert result.quality_report is not None
        assert result.generation_time_seconds > 0

    @patch("app.agents.serp_agent.structured_completion")
    @patch("app.agents.outline_agent.structured_completion")
    @patch("app.agents.writer_agent.chat_completion")
    @patch("app.agents.writer_agent.structured_completion")
    async def test_pipeline_creates_job(
        self, mock_writer_struct, mock_writer_chat, mock_outline, mock_serp
    ):
        """Pipeline should persist a completed job."""
        from app.models.schemas import SERPAnalysis, ArticleOutline
        from app.services.job_store import job_store
        from app.agents.writer_agent import _LinkingOutput, _MetaOutput

        mock_serp.return_value = SERPAnalysis.model_validate_json(_make_serp_analysis_json())
        mock_outline.return_value = ArticleOutline.model_validate_json(_make_outline_json())
        mock_writer_chat.return_value = _make_article_markdown()
        linking = _LinkingOutput.model_validate_json(_make_linking_json())
        meta = _MetaOutput.model_validate_json(_make_meta_json())
        mock_writer_struct.side_effect = [linking, meta] * 3

        request = ArticleRequest(topic="job tracking test")
        provider = MockSERPProvider()
        result = await run_pipeline(request, serp_provider=provider)

        # Find the job
        jobs = job_store.list_jobs(status=JobStatus.COMPLETED)
        matching = [j for j in jobs if j.request.topic == "job tracking test"]
        assert len(matching) >= 1
        assert matching[0].result is not None

    @patch("app.agents.serp_agent.structured_completion")
    async def test_pipeline_fails_gracefully(self, mock_serp):
        """Pipeline failure should be captured in job status."""
        from app.services.job_store import job_store

        mock_serp.side_effect = Exception("LLM exploded")

        request = ArticleRequest(topic="failure test pipeline")
        provider = MockSERPProvider()
        with pytest.raises(Exception, match="LLM exploded"):
            await run_pipeline(request, serp_provider=provider)

        jobs = job_store.list_jobs(status=JobStatus.FAILED)
        matching = [j for j in jobs if j.request.topic == "failure test pipeline"]
        assert len(matching) >= 1
        assert "LLM exploded" in matching[0].error


@pytest.mark.asyncio
class TestCheckpointResume:
    @patch("app.agents.serp_agent.structured_completion")
    @patch("app.agents.outline_agent.structured_completion")
    @patch("app.agents.writer_agent.chat_completion")
    @patch("app.agents.writer_agent.structured_completion")
    async def test_resume_from_serp_checkpoint(
        self, mock_writer_struct, mock_writer_chat, mock_outline, mock_serp
    ):
        """If SERP data exists in checkpoint, pipeline should skip SERP stage."""
        from app.models.schemas import SERPAnalysis, ArticleOutline
        from app.services.job_store import job_store
        from app.agents.writer_agent import _LinkingOutput, _MetaOutput

        # Pre-populate checkpoint with SERP data
        request = ArticleRequest(topic="resume from serp")
        job = Job(request=request)
        job.checkpoint = JobCheckpoint(
            serp_analysis=SERPAnalysis.model_validate_json(
                _make_serp_analysis_json("resume from serp")
            )
        )
        job_store.save(job)

        # SERP agent should NOT be called
        mock_outline.return_value = ArticleOutline.model_validate_json(_make_outline_json())
        mock_writer_chat.return_value = _make_article_markdown()
        linking = _LinkingOutput.model_validate_json(_make_linking_json())
        meta = _MetaOutput.model_validate_json(_make_meta_json())
        mock_writer_struct.side_effect = [linking, meta] * 3

        result = await run_pipeline(request, job=job, serp_provider=MockSERPProvider())

        # SERP structured_completion should NOT have been called
        mock_serp.assert_not_called()
        assert result.title
