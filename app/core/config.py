"""
Application settings loaded from environment variables.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration from environment variables / .env file."""

    # ── LLM ───────────────────────────────────────────────────────────────
    openai_api_key: str = "sk-mock-key-for-testing"
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None
    llm_max_retries: int = 3
    llm_timeout_seconds: int = 60

    # ── SERP ──────────────────────────────────────────────────────────────
    serp_provider: str = "mock"  # mock | serpapi | valueserp
    serp_api_key: str = ""

    # ── Job Store ─────────────────────────────────────────────────────────
    job_store_dir: str = str(Path.home() / ".seo_agent_jobs")

    # ── Quality ───────────────────────────────────────────────────────────
    quality_threshold: float = 6.0
    max_revision_rounds: int = 2

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
