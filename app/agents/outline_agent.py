"""
Outline Agent — creates a structured article outline from SERP analysis.

Uses the themes, subtopics, and keyword data from the SERP agent
to produce an H1/H2/H3 outline with word count allocations.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.models.schemas import ArticleOutline, SERPAnalysis
from app.services.llm_service import structured_completion

logger = get_logger(__name__)

OUTLINE_SYSTEM_PROMPT = """You are an expert SEO content strategist. Given an analysis of top search results for a topic, create a comprehensive article outline.

Requirements:
1. EXACTLY ONE H1 heading (the article title — must include the primary keyword)
2. At least 5 H2 headings covering the main subtopics
3. H3 sub-headings under relevant H2s for depth
4. Allocate realistic word counts per section (should total near the target)
5. Include an Introduction section at the start
6. Include a FAQ section populated from search-derived questions
7. Include a Conclusion section at the end
8. List keywords to naturally include in each section
9. Identify the search intent (informational, commercial, navigational, transactional)

The outline should address the same search intent as top-ranking content while filling identified content gaps."""


async def generate_outline(
    serp_analysis: SERPAnalysis,
    target_word_count: int,
    language: str = "en",
) -> ArticleOutline:
    """
    Generate a structured article outline from SERP analysis.

    The outline includes heading hierarchy, per-section word counts,
    keyword assignments, and search intent classification.
    """
    user_prompt = (
        f"Create an article outline based on this SERP analysis:\n\n"
        f"Primary Keyword: {serp_analysis.primary_keyword}\n"
        f"Secondary Keywords: {', '.join(serp_analysis.secondary_keywords)}\n"
        f"Common Themes: {', '.join(serp_analysis.common_themes)}\n"
        f"Subtopics to Cover: {', '.join(serp_analysis.common_subtopics)}\n"
        f"Content Gaps: {', '.join(serp_analysis.content_gaps)}\n"
        f"FAQ Questions: {'; '.join(serp_analysis.faq_questions)}\n"
        f"Common Title Patterns: {', '.join(serp_analysis.common_title_patterns)}\n\n"
        f"Target word count: {target_word_count}\n"
        f"Language: {language}\n"
    )

    logger.info(
        "Generating outline for '%s' (target %d words)",
        serp_analysis.primary_keyword,
        target_word_count,
    )

    outline = await structured_completion(
        system_prompt=OUTLINE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=ArticleOutline,
    )

    logger.info(
        "Outline generated: '%s' with %d headings, target %d words",
        outline.title,
        len(outline.headings),
        outline.target_total_words,
    )
    return outline
