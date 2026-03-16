"""
Shared test fixtures for the SEO Article Generator test suite.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.models.schemas import (
    ArticleOutline,
    ArticleRequest,
    ExternalReference,
    FAQItem,
    GeneratedArticle,
    InternalLink,
    Language,
    OutlineHeading,
    SEOMetadata,
    SERPAnalysis,
    SERPResult,
)


@pytest.fixture
def sample_request():
    return ArticleRequest(
        topic="best productivity tools for remote teams",
        target_word_count=1500,
        language=Language.EN,
    )


@pytest.fixture
def sample_serp_results():
    return [
        SERPResult(
            rank=i,
            url=f"https://example{i}.com/article",
            title=f"Test Article Title {i} About Productivity Tools for Remote Teams",
            snippet=f"Snippet {i}: productivity tools for remote teams information.",
        )
        for i in range(1, 11)
    ]


@pytest.fixture
def sample_serp_analysis(sample_serp_results):
    return SERPAnalysis(
        query="best productivity tools for remote teams",
        results=sample_serp_results,
        common_themes=[
            "Project management tools",
            "Communication platforms",
            "Time tracking software",
            "AI-powered productivity",
        ],
        common_subtopics=[
            "Asana", "Trello", "Slack", "Zoom", "Notion",
        ],
        avg_title_length=55.0,
        common_title_patterns=["N Best X", "Top X for Y"],
        content_gaps=["AI-powered automation", "Budget comparison"],
        faq_questions=[
            "What is the best free productivity tool?",
            "How do remote teams stay productive?",
            "What tools do successful remote companies use?",
        ],
        primary_keyword="productivity tools for remote teams",
        secondary_keywords=["remote work tools", "team collaboration", "project management"],
    )


@pytest.fixture
def sample_outline():
    return ArticleOutline(
        title="Best Productivity Tools for Remote Teams in 2025",
        headings=[
            OutlineHeading(level=1, text="Best Productivity Tools for Remote Teams in 2025", target_word_count=50),
            OutlineHeading(level=2, text="Introduction", target_word_count=200, keywords_to_include=["productivity tools for remote teams"]),
            OutlineHeading(level=2, text="Top Project Management Tools", target_word_count=300, keywords_to_include=["project management"]),
            OutlineHeading(level=3, text="Asana", target_word_count=100),
            OutlineHeading(level=3, text="Trello", target_word_count=100),
            OutlineHeading(level=2, text="Communication Platforms", target_word_count=250, keywords_to_include=["team collaboration"]),
            OutlineHeading(level=2, text="Time Tracking", target_word_count=200),
            OutlineHeading(level=2, text="AI-Powered Productivity Tools", target_word_count=200),
            OutlineHeading(level=2, text="FAQ", target_word_count=150),
            OutlineHeading(level=2, text="Conclusion", target_word_count=100),
        ],
        target_total_words=1500,
        search_intent="commercial investigation",
        tone="informative, authoritative",
    )


@pytest.fixture
def sample_seo_metadata():
    return SEOMetadata(
        title_tag="Best Productivity Tools for Remote Teams 2025",
        meta_description="Discover the best productivity tools for remote teams. Compare project management, communication, and AI solutions.",
        primary_keyword="productivity tools for remote teams",
        secondary_keywords=["remote work tools", "team collaboration", "project management"],
        keyword_density={"productivity tools for remote teams": 1.2, "remote work tools": 0.5},
    )


@pytest.fixture
def sample_article(sample_outline, sample_seo_metadata):
    markdown = """# Best Productivity Tools for Remote Teams in 2025

## Introduction

Finding the right productivity tools for remote teams can transform how your organization operates. In this guide, we cover the best solutions for distributed teams in 2025. Remote work demands specialized tools that bridge the gap between office and home environments.

## Top Project Management Tools

Project management is essential for remote teams to stay organized and meet deadlines. The right tool helps track progress and assign work effectively across different time zones.

### Asana

Asana provides a flexible workspace with timeline views and automation capabilities that help remote teams coordinate their work efficiently.

### Trello

Trello uses kanban boards for visual task management, making it easy for distributed teams to track progress at a glance.

## Communication Platforms

Effective team collaboration requires seamless communication tools. Slack, Microsoft Teams, and Zoom each serve different needs for remote teams looking to stay connected.

## Time Tracking

Time tracking helps remote teams maintain accountability and understand where work hours are invested. Tools like Toggl and Harvest make this easy.

## AI-Powered Productivity Tools

AI is reshaping how remote teams work. Tools like Notion AI and Motion automate repetitive tasks, helping teams focus on high-value work.

## FAQ

### What is the best free productivity tool?

Trello and Notion both offer generous free tiers suitable for small remote teams. Trello provides unlimited boards, while Notion offers a complete workspace.

### How do remote teams stay productive?

By combining the right tools with clear processes and regular communication. Set clear expectations and use async communication when possible.

### What tools do successful remote companies use?

Companies like GitLab, Zapier, and Buffer rely on Slack for communication, Notion for documentation, and Linear or Asana for project management.

## Conclusion

Choosing the right productivity tools for remote teams requires understanding your unique needs. Start with communication, add project management, and scale from there as your team grows.
"""

    return GeneratedArticle(
        title="Best Productivity Tools for Remote Teams in 2025",
        content_html="<h1>Best Productivity Tools</h1><p>Article content...</p>",
        content_markdown=markdown,
        seo_metadata=sample_seo_metadata,
        outline=sample_outline,
        internal_links=[
            InternalLink(anchor_text="project management guide", suggested_target_page="/project-management", context="Introduction"),
            InternalLink(anchor_text="remote work best practices", suggested_target_page="/remote-work", context="Communication"),
            InternalLink(anchor_text="team building activities", suggested_target_page="/team-building", context="Conclusion"),
        ],
        external_references=[
            ExternalReference(title="Buffer Remote Work Report", url="https://buffer.com/remote-work", authority_reason="Industry report", placement_context="Introduction"),
            ExternalReference(title="Harvard Business Review", url="https://hbr.org/remote-teams", authority_reason="Academic credibility", placement_context="Communication"),
        ],
        faq_section=[
            FAQItem(question="What is the best free productivity tool?", answer="Trello and Notion both offer generous free tiers."),
            FAQItem(question="How do remote teams stay productive?", answer="By combining tools with clear processes."),
            FAQItem(question="What tools do successful remote companies use?", answer="Slack, Notion, and Asana are popular choices."),
        ],
        word_count=1450,
        generation_time_seconds=25.0,
    )


@pytest.fixture
def tmp_job_store(tmp_path):
    """Create a temporary job store for test isolation."""
    from app.services.job_store import JobStore
    return JobStore(store_dir=str(tmp_path / "test_jobs"))
