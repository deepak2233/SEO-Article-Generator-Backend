"""
Writer Agent — produces the full article with linking strategy and SEO metadata.

Three-step process:
  1. Write the markdown article body from the outline
  2. Generate internal + external linking strategy
  3. Generate SEO metadata (title tag, meta description, keywords)

Supports revision feedback for quality improvement loops.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.models.schemas import (
    ArticleOutline,
    ExternalReference,
    FAQItem,
    GeneratedArticle,
    InternalLink,
    SEOMetadata,
    SERPAnalysis,
)
from app.services.llm_service import chat_completion, structured_completion

logger = get_logger(__name__)


# ─── Internal models for structured LLM responses ─────────────────────────


class _LinkingOutput(BaseModel):
    """Internal model for linking strategy LLM response."""
    internal_links: list[InternalLink] = Field(default_factory=list)
    external_references: list[ExternalReference] = Field(default_factory=list)


class _MetaOutput(BaseModel):
    """Internal model for SEO metadata LLM response."""
    title_tag: str = Field(..., max_length=70)
    meta_description: str = Field(..., max_length=160)
    primary_keyword: str
    secondary_keywords: list[str] = Field(default_factory=list)


# ─── System prompts ───────────────────────────────────────────────────────

WRITER_SYSTEM_PROMPT = """You are an expert SEO content writer. Write a complete, publish-ready article in Markdown format.

Requirements:
1. Follow the provided outline exactly (headings, structure)
2. Use the primary keyword naturally in the title, first paragraph, and several headings
3. Include secondary keywords organically throughout
4. Write in a conversational but authoritative tone — like a knowledgeable friend, not a content mill bot
5. Use proper Markdown: # for H1, ## for H2, ### for H3
6. Include transition sentences between sections
7. Make the introduction engaging and include the primary keyword in the first 100 words
8. Each section should provide genuine value and specific examples
9. The FAQ section should have detailed, helpful answers
10. The conclusion should summarize key points and include a call to action

Target word count: {target_word_count} words.
Language: {language}

IMPORTANT: Return ONLY the Markdown article text, no JSON wrapping."""

LINKING_SYSTEM_PROMPT = """You are an SEO link strategist. Given an article and its topic, suggest:

1. Internal links (3-5): Anchor text + suggested target page URL/topic. These should link to related content the publishing site would likely have.
2. External references (2-4): Authoritative sources to cite. Include the source title, URL, why it's authoritative, and where in the article to place it.

Choose links that add genuine value and credibility. External sources should be well-known publications, industry reports, or academic studies."""

META_SYSTEM_PROMPT = """You are an SEO metadata specialist. Given an article and its primary keyword, generate:

1. Title tag (30-60 characters): Include the primary keyword, make it compelling
2. Meta description (120-155 characters): Summarize the article, include primary keyword, add a call to action
3. Primary keyword: The main keyword the article targets
4. Secondary keywords: 3-5 related keywords used in the article"""


# ─── Core writer function ─────────────────────────────────────────────────


async def write_article(
    outline: ArticleOutline,
    serp_analysis: SERPAnalysis,
    target_word_count: int,
    language: str = "en",
    revision_feedback: str | None = None,
) -> GeneratedArticle:
    """
    Write a complete article from an outline and SERP analysis.

    Three async steps:
      1. Generate markdown body
      2. Generate linking strategy
      3. Generate SEO metadata

    If revision_feedback is provided, includes it in the writing prompt
    so the LLM addresses quality issues.
    """
    # ── Step 1: Write the article body ────────────────────────────────────
    outline_text = _format_outline(outline)
    system = WRITER_SYSTEM_PROMPT.format(
        target_word_count=target_word_count,
        language=language,
    )

    user_prompt = (
        f"Write a complete article based on this outline:\n\n"
        f"{outline_text}\n\n"
        f"Primary Keyword: {serp_analysis.primary_keyword}\n"
        f"Secondary Keywords: {', '.join(serp_analysis.secondary_keywords)}\n"
        f"Common Themes to Address: {', '.join(serp_analysis.common_themes)}\n"
    )

    if revision_feedback:
        user_prompt += f"\n\nREVISION FEEDBACK — Please address these issues:\n{revision_feedback}\n"

    logger.info("Step 1/3: Writing article body (target %d words)", target_word_count)
    markdown = await chat_completion(
        system_prompt=system,
        user_prompt=user_prompt,
        max_tokens=8192,
    )

    # ── Step 2: Generate linking strategy ─────────────────────────────────
    logger.info("Step 2/3: Generating linking strategy")
    linking = await structured_completion(
        system_prompt=LINKING_SYSTEM_PROMPT,
        user_prompt=f"Article topic: {serp_analysis.primary_keyword}\n\nArticle:\n{markdown[:2000]}...",
        response_model=_LinkingOutput,
    )

    # ── Step 3: Generate SEO metadata ─────────────────────────────────────
    logger.info("Step 3/3: Generating SEO metadata")
    meta_output = await structured_completion(
        system_prompt=META_SYSTEM_PROMPT,
        user_prompt=(
            f"Primary keyword: {serp_analysis.primary_keyword}\n"
            f"Article title: {outline.title}\n"
            f"Article intro:\n{markdown[:500]}"
        ),
        response_model=_MetaOutput,
    )

    # ── Assemble the final article ────────────────────────────────────────
    word_count = len(re.findall(r"\b\w+\b", markdown))
    faq_items = _extract_faqs(markdown, serp_analysis)

    # Build simple HTML from markdown
    html = _markdown_to_simple_html(markdown)

    # Compute keyword density
    text_lower = markdown.lower()
    total_words = max(1, word_count)
    kw_density = {}
    for kw in [meta_output.primary_keyword] + meta_output.secondary_keywords:
        count = text_lower.count(kw.lower())
        kw_density[kw] = round((count / total_words) * 100, 2)

    seo_metadata = SEOMetadata(
        title_tag=meta_output.title_tag[:70],
        meta_description=meta_output.meta_description[:160],
        primary_keyword=meta_output.primary_keyword,
        secondary_keywords=meta_output.secondary_keywords,
        keyword_density=kw_density,
    )

    article = GeneratedArticle(
        title=outline.title,
        content_html=html,
        content_markdown=markdown,
        seo_metadata=seo_metadata,
        outline=outline,
        internal_links=linking.internal_links,
        external_references=linking.external_references,
        faq_section=faq_items,
        word_count=word_count,
    )

    logger.info(
        "Article written: '%s' — %d words, %d internal links, %d external refs",
        article.title, word_count,
        len(linking.internal_links), len(linking.external_references),
    )
    return article


# ─── Helpers ──────────────────────────────────────────────────────────────


def _format_outline(outline: ArticleOutline) -> str:
    """Format outline headings for the LLM prompt."""
    lines = [f"Title: {outline.title}\n"]
    for h in outline.headings:
        prefix = "#" * h.level
        lines.append(f"{prefix} {h.text}")
        if h.keywords_to_include:
            lines.append(f"  Keywords: {', '.join(h.keywords_to_include)}")
        if h.notes:
            lines.append(f"  Notes: {h.notes}")
        lines.append(f"  Target: ~{h.target_word_count} words")
    return "\n".join(lines)


def _extract_faqs(markdown: str, serp_analysis: SERPAnalysis) -> list[FAQItem]:
    """
    Extract FAQ items from the article markdown.
    Looks for H3 headings under the FAQ section that are questions,
    and pairs them with the following paragraph text.
    """
    faqs = []
    lines = markdown.split("\n")
    in_faq = False
    current_question = None

    for line in lines:
        stripped = line.strip()
        if re.match(r"^##\s+FAQ", stripped, re.IGNORECASE):
            in_faq = True
            continue
        if in_faq and re.match(r"^##\s+", stripped) and not re.match(r"^###", stripped):
            break  # New H2 = end of FAQ section

        if in_faq and re.match(r"^###\s+", stripped):
            if current_question:
                faqs.append(current_question)
            question_text = re.sub(r"^###\s+", "", stripped).strip()
            current_question = FAQItem(question=question_text, answer="")
        elif in_faq and current_question and stripped:
            if current_question.answer:
                current_question.answer += " " + stripped
            else:
                current_question.answer = stripped

    if current_question and current_question.answer:
        faqs.append(current_question)

    # If extraction didn't find FAQs in the markdown, use SERP questions
    if not faqs and serp_analysis.faq_questions:
        for q in serp_analysis.faq_questions[:3]:
            faqs.append(FAQItem(
                question=q,
                answer="See the relevant section in the article above for details.",
            ))

    return faqs


def _markdown_to_simple_html(markdown: str) -> str:
    """Very simple markdown → HTML conversion for headings and paragraphs."""
    html_lines = []
    for line in markdown.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # Headings
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2)
            html_lines.append(f"<h{level}>{text}</h{level}>")
            continue

        # Regular paragraphs
        # Bold
        stripped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
        # Italic
        stripped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", stripped)

        html_lines.append(f"<p>{stripped}</p>")

    return "\n".join(html_lines)
