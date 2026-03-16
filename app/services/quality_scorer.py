"""
Content quality scorer.

Evaluates generated articles against SEO best practices using
algorithmic checks (no LLM needed). This gives fast, deterministic
quality signals.

Dimensions scored (0-10 each):
  1. Keyword presence — primary keyword in title, intro, headings
  2. Heading structure — proper H1→H2→H3 hierarchy, no skipped levels
  3. Word count accuracy — closeness to target
  4. Readability — Flesch-Kincaid approximation
  5. Content depth — subtopic coverage, section count
  6. Meta quality — title tag length, meta description length
"""

from __future__ import annotations

import math
import re

from app.core.logging import get_logger
from app.models.schemas import (
    ContentQualityReport,
    GeneratedArticle,
    QualityDimension,
)

logger = get_logger(__name__)


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _count_sentences(text: str) -> int:
    return max(1, len(re.split(r"[.!?]+", text)))


def _count_syllables(word: str) -> int:
    """Rough English syllable count."""
    word = word.lower().strip()
    if len(word) <= 3:
        return 1
    word = re.sub(r"(?:es|ed|e)$", "", word) or word
    vowels = re.findall(r"[aeiouy]+", word)
    return max(1, len(vowels))


def _flesch_reading_ease(text: str) -> float:
    """Simplified Flesch Reading Ease score (0-100, higher = easier)."""
    words = re.findall(r"\b\w+\b", text)
    if not words:
        return 0.0
    sentences = _count_sentences(text)
    syllables = sum(_count_syllables(w) for w in words)
    score = 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words))
    return max(0.0, min(100.0, score))


def _extract_headings(markdown: str) -> list[tuple[int, str]]:
    """Extract (level, text) tuples from markdown headings."""
    headings: list[tuple[int, str]] = []
    for line in markdown.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if m:
            headings.append((len(m.group(1)), m.group(2).strip()))
    return headings


def score_article(article: GeneratedArticle) -> ContentQualityReport:
    """Run all quality checks and return a report."""
    md = article.content_markdown
    meta = article.seo_metadata
    target_wc = article.outline.target_total_words
    primary_kw = meta.primary_keyword.lower()

    dimensions: list[QualityDimension] = []
    suggestions: list[str] = []

    # ── 1. Keyword Presence ───────────────────────────────────────────────
    kw_score = 0.0
    kw_in_title = primary_kw in article.title.lower()
    intro_text = md[:500].lower() if md else ""
    kw_in_intro = primary_kw in intro_text
    headings = _extract_headings(md)
    kw_in_headings = any(primary_kw in h.lower() for _, h in headings)

    if kw_in_title:
        kw_score += 4.0
    else:
        suggestions.append("Include primary keyword in the article title")
    if kw_in_intro:
        kw_score += 3.0
    else:
        suggestions.append("Include primary keyword in the introduction paragraph")
    if kw_in_headings:
        kw_score += 3.0
    else:
        suggestions.append("Include primary keyword in at least one H2/H3 heading")

    dimensions.append(QualityDimension(
        name="Keyword Presence",
        score=kw_score,
        feedback=f"Title: {'✓' if kw_in_title else '✗'}, Intro: {'✓' if kw_in_intro else '✗'}, Headings: {'✓' if kw_in_headings else '✗'}",
        passed=kw_score >= 7.0,
    ))

    # ── 2. Heading Structure ──────────────────────────────────────────────
    h_score = 10.0
    h_feedback = []
    h1_count = sum(1 for lv, _ in headings if lv == 1)
    if h1_count != 1:
        h_score -= 3.0
        h_feedback.append(f"Expected 1 H1, found {h1_count}")
    h2_count = sum(1 for lv, _ in headings if lv == 2)
    if h2_count < 3:
        h_score -= 2.0
        h_feedback.append(f"Only {h2_count} H2 sections (recommend ≥3)")
        suggestions.append("Add more H2 sections for better content structure")

    # Check for level skips (e.g. H1 → H3)
    prev_level = 0
    for lv, _ in headings:
        if lv > prev_level + 1 and prev_level > 0:
            h_score -= 1.5
            h_feedback.append(f"Skipped heading level: H{prev_level} → H{lv}")
            break
        prev_level = lv

    h_score = max(0.0, h_score)
    dimensions.append(QualityDimension(
        name="Heading Structure",
        score=h_score,
        feedback="; ".join(h_feedback) if h_feedback else "Proper heading hierarchy",
        passed=h_score >= 6.0,
    ))

    # ── 3. Word Count ─────────────────────────────────────────────────────
    actual_wc = _count_words(md)
    ratio = actual_wc / max(1, target_wc)
    # Perfect = 1.0, penalize deviations
    wc_score = max(0.0, 10.0 - abs(1.0 - ratio) * 15.0)
    wc_feedback = f"{actual_wc} words (target {target_wc}, ratio {ratio:.2f})"
    if ratio < 0.7:
        suggestions.append(f"Article is too short ({actual_wc}/{target_wc} words)")
    elif ratio > 1.4:
        suggestions.append(f"Article is too long ({actual_wc}/{target_wc} words)")
    dimensions.append(QualityDimension(
        name="Word Count",
        score=wc_score,
        feedback=wc_feedback,
        passed=0.7 <= ratio <= 1.4,
    ))

    # ── 4. Readability ────────────────────────────────────────────────────
    fre = _flesch_reading_ease(md)
    # Target FRE 50-70 for web content
    if 45 <= fre <= 75:
        read_score = 10.0
    elif 30 <= fre < 45 or 75 < fre <= 85:
        read_score = 7.0
    else:
        read_score = 4.0
        suggestions.append(f"Readability score ({fre:.0f}) is outside optimal range (45-75)")
    dimensions.append(QualityDimension(
        name="Readability",
        score=read_score,
        feedback=f"Flesch Reading Ease: {fre:.1f}",
        passed=read_score >= 6.0,
    ))

    # ── 5. Content Depth ──────────────────────────────────────────────────
    section_count = h2_count + sum(1 for lv, _ in headings if lv == 3)
    depth_score = min(10.0, section_count * 1.2)
    if section_count < 4:
        suggestions.append("Add more sections/subtopics for greater content depth")
    dimensions.append(QualityDimension(
        name="Content Depth",
        score=depth_score,
        feedback=f"{section_count} content sections (H2+H3)",
        passed=depth_score >= 5.0,
    ))

    # ── 6. Meta Quality ──────────────────────────────────────────────────
    meta_score = 10.0
    meta_fb = []
    title_len = len(meta.title_tag)
    if title_len < 30:
        meta_score -= 3.0
        meta_fb.append(f"Title tag too short ({title_len} chars)")
    elif title_len > 60:
        meta_score -= 1.5
        meta_fb.append(f"Title tag slightly long ({title_len} chars)")

    desc_len = len(meta.meta_description)
    if desc_len < 70:
        meta_score -= 3.0
        meta_fb.append(f"Meta description too short ({desc_len} chars)")
        suggestions.append("Expand meta description to 120-155 characters")
    elif desc_len > 160:
        meta_score -= 1.5
        meta_fb.append(f"Meta description too long ({desc_len} chars)")

    if primary_kw not in meta.title_tag.lower():
        meta_score -= 2.0
        meta_fb.append("Primary keyword missing from title tag")
    if primary_kw not in meta.meta_description.lower():
        meta_score -= 1.0
        meta_fb.append("Primary keyword missing from meta description")

    meta_score = max(0.0, meta_score)
    dimensions.append(QualityDimension(
        name="Meta Quality",
        score=meta_score,
        feedback="; ".join(meta_fb) if meta_fb else "Meta tags well-optimized",
        passed=meta_score >= 6.0,
    ))

    # ── Aggregate ─────────────────────────────────────────────────────────
    overall = sum(d.score for d in dimensions) / len(dimensions)
    passed = all(d.passed for d in dimensions) and overall >= 6.0

    report = ContentQualityReport(
        overall_score=round(overall, 2),
        dimensions=dimensions,
        passed=passed,
        revision_suggestions=suggestions,
        keyword_in_title=kw_in_title,
        keyword_in_intro=kw_in_intro,
        has_proper_h_structure=h_score >= 6.0,
        word_count=actual_wc,
        target_word_count=target_wc,
    )
    logger.info(
        "Quality report: overall=%.2f passed=%s dims=%s",
        overall, passed,
        {d.name: d.score for d in dimensions},
    )
    return report
