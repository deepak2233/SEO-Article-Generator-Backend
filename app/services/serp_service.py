"""
SERP (Search Engine Results Page) service.

Provides search result data for the SERP agent to analyze.
Supports multiple providers behind a common interface:
  - MockSERPProvider: realistic mock data (no API key needed)
  - SerpAPISERPProvider: real SerpAPI integration
"""

from __future__ import annotations

import abc

from app.core.config import settings
from app.core.exceptions import SERPServiceError
from app.core.logging import get_logger
from app.models.schemas import SERPResult

logger = get_logger(__name__)


class SERPProvider(abc.ABC):
    """Abstract base class for SERP data providers."""

    @abc.abstractmethod
    async def search(self, query: str, num_results: int = 10) -> list[SERPResult]:
        """Fetch top search results for a query."""


class MockSERPProvider(SERPProvider):
    """
    Returns realistic mock SERP data for any query.
    Great for testing and development — no API key needed.
    """

    async def search(self, query: str, num_results: int = 10) -> list[SERPResult]:
        logger.info("MockSERPProvider: generating %d results for '%s'", num_results, query)
        mock_results = [
            SERPResult(
                rank=1,
                url="https://www.techradar.com/best/productivity-tools",
                title="15 Best Productivity Tools for Remote Teams in 2025",
                snippet="Discover the top productivity tools that help remote teams collaborate effectively. From project management to communication platforms.",
            ),
            SERPResult(
                rank=2,
                url="https://www.forbes.com/advisor/business/remote-work-tools/",
                title="Best Remote Work Tools: Top Picks for 2025 | Forbes",
                snippet="Our experts tested 50+ remote work tools. Here are the best picks for project management, video conferencing, and team collaboration.",
            ),
            SERPResult(
                rank=3,
                url="https://zapier.com/blog/best-remote-work-tools/",
                title="The 25 Best Remote Work Tools in 2025 | Zapier",
                snippet="Working remotely? These are the essential tools every distributed team needs for communication, project management, and file sharing.",
            ),
            SERPResult(
                rank=4,
                url="https://www.hubspot.com/productivity-tools",
                title="20 Productivity Tools That Will Make Your Team More Efficient",
                snippet="Boost your team's productivity with these powerful tools. Includes free and paid options for task management, time tracking, and collaboration.",
            ),
            SERPResult(
                rank=5,
                url="https://monday.com/blog/remote-work/productivity-tools/",
                title="Top 10 Productivity Tools for Remote Teams - monday.com",
                snippet="Managing a remote team? These productivity tools help you stay organized, track progress, and keep everyone aligned.",
            ),
            SERPResult(
                rank=6,
                url="https://www.pcmag.com/picks/the-best-project-management-software",
                title="The Best Project Management Software for 2025 | PCMag",
                snippet="We tested the top project management apps. Here's how Asana, Trello, Monday, and ClickUp compare for remote teams.",
            ),
            SERPResult(
                rank=7,
                url="https://buffer.com/resources/remote-work-tools/",
                title="Our Favorite Remote Work Tools at Buffer (2025 Update)",
                snippet="As a fully remote company, Buffer relies on these tools daily. Here's our real-world review of what actually works.",
            ),
            SERPResult(
                rank=8,
                url="https://www.atlassian.com/blog/productivity/remote-team-tools",
                title="Essential Tools for Remote Team Productivity | Atlassian",
                snippet="Learn how distributed teams at Atlassian stay productive with the right combination of communication, project tracking, and documentation tools.",
            ),
            SERPResult(
                rank=9,
                url="https://www.notion.so/blog/remote-work-tools",
                title="Remote Work Tools: The Complete Guide for 2025",
                snippet="From async communication to knowledge management — a comprehensive guide to building your remote team's tool stack.",
            ),
            SERPResult(
                rank=10,
                url="https://hbr.org/2024/05/the-tools-that-make-remote-work-actually-work",
                title="The Tools That Make Remote Work Actually Work - HBR",
                snippet="Research-backed recommendations for the tools and practices that lead to sustainable remote work productivity.",
            ),
        ]
        return mock_results[:num_results]


class SerpAPISERPProvider(SERPProvider):
    """
    Real SERP data via SerpAPI (serpapi.com).
    Requires SERP_API_KEY in environment.
    """

    async def search(self, query: str, num_results: int = 10) -> list[SERPResult]:
        if not settings.serp_api_key:
            raise SERPServiceError("SERP_API_KEY not configured for SerpAPI provider")

        try:
            import httpx
        except ImportError:
            raise SERPServiceError("httpx not installed. Run: pip install httpx")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://serpapi.com/search",
                    params={
                        "q": query,
                        "api_key": settings.serp_api_key,
                        "num": num_results,
                        "engine": "google",
                    },
                )
                response.raise_for_status()
                data = response.json()

            results = []
            for i, item in enumerate(data.get("organic_results", [])[:num_results], 1):
                results.append(
                    SERPResult(
                        rank=i,
                        url=item.get("link", ""),
                        title=item.get("title", ""),
                        snippet=item.get("snippet", ""),
                    )
                )
            return results

        except Exception as exc:
            raise SERPServiceError(f"SerpAPI request failed: {exc}") from exc


def get_serp_provider() -> SERPProvider:
    """Factory function: returns the configured SERP provider."""
    provider_name = settings.serp_provider.lower()
    if provider_name == "mock":
        return MockSERPProvider()
    elif provider_name in ("serpapi", "serp_api"):
        return SerpAPISERPProvider()
    else:
        logger.warning("Unknown SERP provider '%s', falling back to mock", provider_name)
        return MockSERPProvider()
