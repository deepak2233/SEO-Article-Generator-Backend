"""
SERP Agent — searches and analyzes top search results.

Takes a query, fetches top-10 SERP results via the provider,
then uses an LLM to extract themes, keywords, subtopics,
content gaps, and FAQ questions.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.models.schemas import SERPAnalysis
from app.services.llm_service import structured_completion
from app.services.serp_service import SERPProvider

logger = get_logger(__name__)

SERP_ANALYSIS_SYSTEM_PROMPT = """You are an expert SEO analyst. You will be given a search query and the top 10 search engine results.

Analyze these results and identify:
1. The primary keyword (the main search intent)
2. Secondary keywords (related terms used across results)
3. Common themes across the top-ranking content (4-6 themes)
4. Common subtopics covered (5-8 subtopics)
5. Average title length and common title patterns (e.g. "N Best X", "Complete Guide to Y")
6. Content gaps — topics NOT well covered that could differentiate new content
7. FAQ questions that searchers are likely asking (3-5 questions)

Be specific and actionable. These insights will drive article outline creation."""


async def analyze_serp(
    query: str,
    serp_provider: SERPProvider,
) -> SERPAnalysis:
    """
    Fetch SERP results and analyze them via LLM.

    Returns a structured SERPAnalysis with themes, keywords,
    subtopics, gaps, and FAQ questions extracted from the results.
    """
    logger.info("Fetching SERP results for: '%s'", query)
    results = await serp_provider.search(query, num_results=10)

    # Format results for the LLM
    results_text = f"Search Query: {query}\n\nTop 10 Search Results:\n\n"
    for r in results:
        results_text += (
            f"Rank {r.rank}: {r.title}\n"
            f"  URL: {r.url}\n"
            f"  Snippet: {r.snippet}\n\n"
        )

    logger.info("Analyzing %d SERP results via LLM", len(results))
    analysis = await structured_completion(
        system_prompt=SERP_ANALYSIS_SYSTEM_PROMPT,
        user_prompt=results_text,
        response_model=SERPAnalysis,
    )

    # Ensure the raw results are included in the analysis
    analysis.results = results
    analysis.query = query

    logger.info(
        "SERP analysis complete: primary_kw='%s', %d themes, %d subtopics, %d FAQs",
        analysis.primary_keyword,
        len(analysis.common_themes),
        len(analysis.common_subtopics),
        len(analysis.faq_questions),
    )
    return analysis
