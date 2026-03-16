"""
Tests for Pydantic models — validation, edge cases, serialization.
"""

import json
import uuid

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    ArticleOutline,
    ArticleRequest,
    ContentQualityReport,
    FAQItem,
    GeneratedArticle,
    InternalLink,
    Job,
    JobCheckpoint,
    JobStatus,
    Language,
    OutlineHeading,
    QualityDimension,
    SEOMetadata,
    SERPAnalysis,
    SERPResult,
)


class TestArticleRequest:
    def test_valid_request(self):
        req = ArticleRequest(topic="best CRM software for startups")
        assert req.topic == "best CRM software for startups"
        assert req.target_word_count == 1500
        assert req.language == Language.EN

    def test_custom_word_count(self):
        req = ArticleRequest(topic="test", target_word_count=3000, language=Language.ES)
        assert req.target_word_count == 3000
        assert req.language == Language.ES

    def test_topic_whitespace_normalization(self):
        req = ArticleRequest(topic="  best   tools   for   teams  ")
        assert req.topic == "best tools for teams"

    def test_topic_too_short(self):
        with pytest.raises(ValidationError, match="String should have at least 3 characters"):
            ArticleRequest(topic="ab")

    def test_topic_too_long(self):
        with pytest.raises(ValidationError):
            ArticleRequest(topic="x" * 501)

    def test_word_count_below_minimum(self):
        with pytest.raises(ValidationError):
            ArticleRequest(topic="valid topic", target_word_count=100)

    def test_word_count_above_maximum(self):
        with pytest.raises(ValidationError):
            ArticleRequest(topic="valid topic", target_word_count=50000)

    def test_invalid_language(self):
        with pytest.raises(ValidationError):
            ArticleRequest(topic="test", language="xx")

    def test_all_languages_valid(self):
        for lang in Language:
            req = ArticleRequest(topic="test topic", language=lang)
            assert req.language == lang

    def test_serialization_roundtrip(self):
        req = ArticleRequest(topic="test topic", target_word_count=2000, language=Language.FR)
        data = req.model_dump_json()
        req2 = ArticleRequest.model_validate_json(data)
        assert req == req2


class TestSERPResult:
    def test_domain_auto_extraction(self):
        result = SERPResult(
            rank=1,
            url="https://www.example.com/path/page",
            title="Test",
            snippet="Test snippet",
        )
        assert result.domain == "www.example.com"

    def test_explicit_domain(self):
        result = SERPResult(
            rank=1,
            url="https://example.com/page",
            title="Test",
            snippet="Snippet",
            domain="custom.domain.com",
        )
        assert result.domain == "custom.domain.com"

    def test_rank_validation(self):
        with pytest.raises(ValidationError):
            SERPResult(rank=0, url="https://x.com", title="T", snippet="S")

    def test_rank_validation_upper_bound(self):
        with pytest.raises(ValidationError):
            SERPResult(rank=101, url="https://x.com", title="T", snippet="S")

    def test_empty_url_no_crash(self):
        result = SERPResult(rank=1, url="", title="T", snippet="S")
        assert result.domain == ""


class TestSERPAnalysis:
    def test_empty_analysis(self):
        analysis = SERPAnalysis(query="test", results=[])
        assert analysis.common_themes == []
        assert analysis.primary_keyword == ""

    def test_full_analysis(self, sample_serp_analysis):
        assert sample_serp_analysis.primary_keyword == "productivity tools for remote teams"
        assert len(sample_serp_analysis.results) == 10
        assert len(sample_serp_analysis.common_themes) == 4
        assert len(sample_serp_analysis.faq_questions) == 3


class TestArticleOutline:
    def test_heading_level_validation(self):
        with pytest.raises(ValidationError):
            OutlineHeading(level=0, text="Bad", target_word_count=100)

    def test_heading_level_5_invalid(self):
        with pytest.raises(ValidationError):
            OutlineHeading(level=5, text="Too deep", target_word_count=100)

    def test_valid_outline(self, sample_outline):
        assert sample_outline.title.startswith("Best")
        assert len(sample_outline.headings) == 10
        h1_count = sum(1 for h in sample_outline.headings if h.level == 1)
        assert h1_count == 1


class TestSEOMetadata:
    def test_title_tag_max_length(self):
        with pytest.raises(ValidationError):
            SEOMetadata(
                title_tag="x" * 71,
                meta_description="Valid",
                primary_keyword="test",
            )

    def test_meta_description_max_length(self):
        with pytest.raises(ValidationError):
            SEOMetadata(
                title_tag="Valid",
                meta_description="x" * 161,
                primary_keyword="test",
            )

    def test_valid_metadata(self, sample_seo_metadata):
        assert len(sample_seo_metadata.title_tag) <= 70
        assert len(sample_seo_metadata.meta_description) <= 160


class TestQualityReport:
    def test_score_bounds(self):
        with pytest.raises(ValidationError):
            ContentQualityReport(overall_score=11.0)

    def test_negative_score(self):
        with pytest.raises(ValidationError):
            ContentQualityReport(overall_score=-1.0)

    def test_dimension_score_bounds(self):
        with pytest.raises(ValidationError):
            QualityDimension(name="test", score=11.0)

    def test_valid_report(self):
        report = ContentQualityReport(
            overall_score=8.5,
            dimensions=[QualityDimension(name="kw", score=9.0, feedback="good")],
            passed=True,
            word_count=1500,
            target_word_count=1500,
        )
        assert report.passed is True


class TestJob:
    def test_job_creation(self, sample_request):
        job = Job(request=sample_request)
        assert job.status == JobStatus.PENDING
        assert job.attempts == 0
        assert job.error is None
        uuid.UUID(job.id)  # Validates UUID format

    def test_status_advance(self, sample_request):
        job = Job(request=sample_request)
        job.advance_status(JobStatus.RESEARCHING)
        assert job.status == JobStatus.RESEARCHING
        assert job.updated_at > job.created_at or job.updated_at == job.created_at

    def test_job_fail(self, sample_request):
        job = Job(request=sample_request)
        job.fail("Something broke")
        assert job.status == JobStatus.FAILED
        assert job.error == "Something broke"

    def test_checkpoint_serialization(self, sample_request, sample_serp_analysis):
        job = Job(request=sample_request)
        job.checkpoint = JobCheckpoint(serp_analysis=sample_serp_analysis)
        data = job.model_dump_json()
        loaded = Job.model_validate_json(data)
        assert loaded.checkpoint.serp_analysis.primary_keyword == "productivity tools for remote teams"

    def test_full_job_serialization(self, sample_request, sample_article):
        job = Job(request=sample_request)
        job.result = sample_article
        job.advance_status(JobStatus.COMPLETED)
        data = job.model_dump_json()
        loaded = Job.model_validate_json(data)
        assert loaded.status == JobStatus.COMPLETED
        assert loaded.result.title == sample_article.title


class TestGeneratedArticle:
    def test_article_structure(self, sample_article):
        assert sample_article.title
        assert sample_article.content_markdown
        assert len(sample_article.internal_links) >= 3
        assert len(sample_article.external_references) >= 2
        assert len(sample_article.faq_section) >= 2

    def test_internal_link_structure(self, sample_article):
        for link in sample_article.internal_links:
            assert link.anchor_text
            assert link.suggested_target_page

    def test_external_reference_structure(self, sample_article):
        for ref in sample_article.external_references:
            assert ref.url.startswith("http")
            assert ref.authority_reason


class TestEdgeCases:
    """Edge cases that a 10+ year engineer would think about."""

    def test_unicode_topic(self):
        req = ArticleRequest(topic="mejores herramientas de productividad", language=Language.ES)
        assert req.topic == "mejores herramientas de productividad"

    def test_topic_with_special_chars(self):
        req = ArticleRequest(topic="C++ vs Rust: which is better?")
        assert "C++" in req.topic

    def test_emoji_in_topic(self):
        req = ArticleRequest(topic="🚀 rocket science basics")
        assert req.topic == "🚀 rocket science basics"

    def test_max_boundary_word_count(self):
        req = ArticleRequest(topic="test", target_word_count=300)
        assert req.target_word_count == 300
        req2 = ArticleRequest(topic="test", target_word_count=10000)
        assert req2.target_word_count == 10000

    def test_serp_result_with_malformed_url(self):
        result = SERPResult(rank=1, url="not-a-url", title="T", snippet="S")
        assert result.domain == ""  # urlparse handles gracefully

    def test_empty_outline_headings(self):
        outline = ArticleOutline(
            title="Test", headings=[], target_total_words=500
        )
        assert len(outline.headings) == 0

    def test_job_checkpoint_empty(self):
        cp = JobCheckpoint()
        assert cp.serp_analysis is None
        assert cp.outline is None
        assert cp.draft_markdown is None

    def test_keyword_density_empty(self):
        meta = SEOMetadata(
            title_tag="Test",
            meta_description="Test description",
            primary_keyword="test",
        )
        assert meta.keyword_density == {}

    def test_faq_item(self):
        faq = FAQItem(question="What is SEO?", answer="Search Engine Optimization.")
        assert faq.question.endswith("?")
