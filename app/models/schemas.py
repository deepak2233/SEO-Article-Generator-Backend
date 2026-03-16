"""
Pydantic models for the SEO Article Generation system.
Structured data models throughout the pipeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING = "pending"
    RESEARCHING = "researching"
    OUTLINING = "outlining"
    WRITING = "writing"
    REVIEWING = "reviewing"
    REVISING = "revising"
    COMPLETED = "completed"
    FAILED = "failed"


class Language(str, Enum):
    EN = "en"
    ES = "es"
    FR = "fr"
    DE = "de"
    PT = "pt"
    IT = "it"
    NL = "nl"
    JA = "ja"
    ZH = "zh"
    KO = "ko"
    HI = "hi"


# ─── Input Models ─────────────────────────────────────────────────────────────

class ArticleRequest(BaseModel):
    """Input: What the user sends to kick off generation."""
    topic: str = Field(..., min_length=3, max_length=500, description="Primary keyword or topic")
    target_word_count: int = Field(default=1500, ge=300, le=10000)
    language: Language = Field(default=Language.EN)

    @field_validator("topic")
    @classmethod
    def clean_topic(cls, v: str) -> str:
        return " ".join(v.split()).strip()


# ─── SERP Models ──────────────────────────────────────────────────────────────

class SERPResult(BaseModel):
    """Single search engine result."""
    rank: int = Field(..., ge=1, le=100)
    url: str
    title: str
    snippet: str
    domain: str = ""

    def model_post_init(self, __context) -> None:
        if not self.domain and self.url:
            from urllib.parse import urlparse
            parsed = urlparse(self.url)
            self.domain = parsed.netloc


class SERPAnalysis(BaseModel):
    """Aggregated analysis of top 10 SERP results."""
    query: str
    results: list[SERPResult]
    common_themes: list[str] = Field(default_factory=list)
    common_subtopics: list[str] = Field(default_factory=list)
    avg_title_length: float = 0.0
    common_title_patterns: list[str] = Field(default_factory=list)
    content_gaps: list[str] = Field(default_factory=list)
    faq_questions: list[str] = Field(default_factory=list)
    primary_keyword: str = ""
    secondary_keywords: list[str] = Field(default_factory=list)


# ─── Outline Models ──────────────────────────────────────────────────────────

class OutlineHeading(BaseModel):
    """Single heading in the article outline."""
    level: int = Field(..., ge=1, le=4, description="H1=1, H2=2, H3=3, H4=4")
    text: str
    target_word_count: int = Field(default=200, ge=50, le=3000)
    keywords_to_include: list[str] = Field(default_factory=list)
    notes: str = ""


class ArticleOutline(BaseModel):
    """Complete structured outline for the article."""
    title: str
    headings: list[OutlineHeading]
    target_total_words: int
    search_intent: str = ""
    tone: str = "informative, authoritative, conversational"


# ─── Linking Models ──────────────────────────────────────────────────────────

class InternalLink(BaseModel):
    """Suggested internal link."""
    anchor_text: str
    suggested_target_page: str
    context: str = Field(default="", description="Where in the article this link fits")


class ExternalReference(BaseModel):
    """External authoritative source to cite."""
    title: str
    url: str
    authority_reason: str
    placement_context: str = Field(default="", description="Where in the article to cite this")


# ─── SEO Metadata ────────────────────────────────────────────────────────────

class SEOMetadata(BaseModel):
    """SEO metadata for the article."""
    title_tag: str = Field(..., max_length=70)
    meta_description: str = Field(..., max_length=160)
    primary_keyword: str
    secondary_keywords: list[str] = Field(default_factory=list)
    keyword_density: dict[str, float] = Field(default_factory=dict, description="keyword -> density %")
    readability_score: float = Field(default=0.0, ge=0.0, le=100.0)


# ─── Quality Score ───────────────────────────────────────────────────────────

class QualityDimension(BaseModel):
    """Score on a single quality dimension."""
    name: str
    score: float = Field(..., ge=0.0, le=10.0)
    feedback: str = ""
    passed: bool = True


class ContentQualityReport(BaseModel):
    """Full quality assessment of a generated article."""
    overall_score: float = Field(..., ge=0.0, le=10.0)
    dimensions: list[QualityDimension] = Field(default_factory=list)
    passed: bool = True
    revision_suggestions: list[str] = Field(default_factory=list)
    keyword_in_title: bool = False
    keyword_in_intro: bool = False
    has_proper_h_structure: bool = False
    word_count: int = 0
    target_word_count: int = 0


# ─── FAQ ─────────────────────────────────────────────────────────────────────

class FAQItem(BaseModel):
    question: str
    answer: str


# ─── Final Article Output ────────────────────────────────────────────────────

class GeneratedArticle(BaseModel):
    """Complete output: the published article with all metadata."""
    title: str
    content_html: str
    content_markdown: str
    seo_metadata: SEOMetadata
    outline: ArticleOutline
    internal_links: list[InternalLink] = Field(default_factory=list)
    external_references: list[ExternalReference] = Field(default_factory=list)
    faq_section: list[FAQItem] = Field(default_factory=list)
    quality_report: Optional[ContentQualityReport] = None
    word_count: int = 0
    generation_time_seconds: float = 0.0


# ─── Job Tracking ────────────────────────────────────────────────────────────

class JobCheckpoint(BaseModel):
    """Serializable checkpoint for crash recovery."""
    serp_analysis: Optional[SERPAnalysis] = None
    outline: Optional[ArticleOutline] = None
    draft_markdown: Optional[str] = None
    quality_report: Optional[ContentQualityReport] = None


class Job(BaseModel):
    """Persistent job with status tracking and crash recovery."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request: ArticleRequest
    status: JobStatus = JobStatus.PENDING
    checkpoint: JobCheckpoint = Field(default_factory=JobCheckpoint)
    result: Optional[GeneratedArticle] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    attempts: int = 0
    max_attempts: int = 3

    def advance_status(self, new_status: JobStatus) -> None:
        self.status = new_status
        self.updated_at = datetime.utcnow()

    def fail(self, error: str) -> None:
        self.error = error
        self.status = JobStatus.FAILED
        self.updated_at = datetime.utcnow()
