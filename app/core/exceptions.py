"""
Custom exception hierarchy for the SEO Article Generator.
"""


class SEOAgentError(Exception):
    """Base exception for all SEO Agent errors."""


class JobNotFoundError(SEOAgentError):
    """Raised when a job ID is not found in the store."""


class QualityThresholdError(SEOAgentError):
    """Raised when quality cannot be met after max retries."""


class LLMServiceError(SEOAgentError):
    """Raised on LLM API failures (after retries exhausted)."""


class SERPServiceError(SEOAgentError):
    """Raised on SERP API failures."""
