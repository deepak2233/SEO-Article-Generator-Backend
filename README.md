# SEO Article Generator — Agent-Based Backend Service

An intelligent, agent-based backend service that generates SEO-optimized articles by analyzing search engine results and producing high-quality, publish-ready content.

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│                        FastAPI REST API                        │
│  POST /articles/generate  GET /jobs/{id}  POST /jobs/{id}/resume│
└──────────────────────────┬─────────────────────────────────────┘
                           │
                   ┌───────▼────────┐
                   │  Orchestrator   │  ← Job management + checkpoint/resume
                   │    Agent        │
                   └───┬───┬───┬────┘
                       │   │   │
           ┌───────────┘   │   └───────────┐
           ▼               ▼               ▼
    ┌──────────┐   ┌──────────┐   ┌──────────────┐
    │  SERP    │   │ Outline  │   │   Writer     │
    │  Agent   │   │  Agent   │   │   Agent      │
    └────┬─────┘   └──────────┘   └──────┬───────┘
         │                                │
    ┌────▼─────┐                  ┌───────▼───────┐
    │  SERP    │                  │   Quality     │
    │ Provider │                  │   Scorer      │
    │(mock/api)│                  │(deterministic)│
    └──────────┘                  └───────────────┘
```

### Agent Pipeline

| Stage | Agent | Description |
|-------|-------|-------------|
| 1 | **SERP Agent** | Fetches top 10 search results, uses LLM to extract themes, keywords, subtopics, content gaps, and FAQ questions |
| 2 | **Outline Agent** | Creates a structured article outline based on SERP analysis, targeting competitive search intent |
| 3 | **Writer Agent** | Generates the full article, linking strategy, and SEO metadata from the outline |
| 4 | **Quality Scorer** | Algorithmic (no LLM) evaluation across 6 dimensions: keyword presence, heading structure, word count, readability, content depth, meta quality |
| 5 | **Revision Loop** | If quality score < threshold, feeds revision suggestions back to the Writer Agent (max 2 rounds) |

Every stage checkpoints to disk, enabling **crash recovery** — if the process dies after SERP collection, it resumes from the outline stage.

## Design Decisions

### Why Agent-Based?
Each agent has a single responsibility and communicates through structured Pydantic models. This makes the pipeline testable in isolation, easy to extend (add a "Fact Checker" agent, swap SERP providers), and debuggable through checkpoints.

### Why Algorithmic Quality Scoring?
Using an LLM to evaluate LLM output creates circular dependencies and non-determinism. The quality scorer uses deterministic heuristics (Flesch-Kincaid readability, heading hierarchy validation, keyword density calculation) that are fast, free, and reproducible.

### Why File-Based Job Persistence?
For a take-home assessment, file-based JSON storage is the right trade-off: zero dependencies (no Redis/Postgres), atomic writes via tmp-then-rename, and trivially inspectable. In production, this would be swapped for a proper database behind the same `JobStore` interface.

### Error Handling Strategy
- **SERP failures**: Graceful degradation with clear error messages; supports multiple providers (mock, SerpAPI, ValueSERP)
- **LLM failures**: Exponential backoff retry (3 attempts), rate-limit awareness, timeout handling
- **Quality failures**: Revision loop with max 2 rounds; if still below threshold, returns best-effort with quality report attached
- **Job failures**: Error captured in job record; job can be resumed via `POST /jobs/{id}/resume`

### Structured Data Throughout
Every inter-agent message is a Pydantic model with strict validation. This catches schema mismatches at boundaries rather than deep inside business logic.

## Project Structure

```
seo-agent/
├── app/
│   ├── agents/               # Agent implementations
│   │   ├── orchestrator.py   # Pipeline controller with checkpoint/resume
│   │   ├── serp_agent.py     # SERP analysis via LLM
│   │   ├── outline_agent.py  # Article outline generation
│   │   └── writer_agent.py   # Full article + links + meta generation
│   ├── api/
│   │   └── routes.py         # FastAPI REST endpoints
│   ├── core/
│   │   ├── config.py         # Settings from environment
│   │   ├── exceptions.py     # Custom exception hierarchy
│   │   └── logging.py        # Structured logging
│   ├── models/
│   │   └── schemas.py        # All Pydantic models (20+ models)
│   ├── services/
│   │   ├── serp_service.py   # SERP providers (mock + real APIs)
│   │   ├── llm_service.py    # LLM abstraction with retry + structured output
│   │   ├── job_store.py      # File-based job persistence
│   │   └── quality_scorer.py # Algorithmic SEO quality evaluation
│   └── main.py               # FastAPI app factory
├── tests/
│   ├── conftest.py           # Shared fixtures
│   ├── test_models.py        # Model validation + edge cases
│   ├── test_serp_service.py  # SERP provider tests
│   ├── test_quality_scorer.py# Quality scoring tests
│   ├── test_job_store.py     # Persistence + recovery tests
│   ├── test_api.py           # API endpoint tests
│   └── test_integration.py   # Full pipeline with mocked LLM
├── examples/
│   └── sample_output.json    # Complete input → output example
├── requirements.txt
├── pyproject.toml            # Pytest config
├── Dockerfile
├── .env.example
└── README.md
```

## Quick Start

### 1. Install

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

For development/testing, the default `SERP_PROVIDER=mock` works without any API keys.

### 3. Run Tests

```bash
pytest
```

This runs the full test suite (~50 tests) including model validation, SERP service, quality scoring, job persistence, API endpoints, and integration tests.

### 4. Start Server

```bash
# With real LLM (requires OPENAI_API_KEY in .env):
uvicorn app.main:app --reload

# API docs available at http://localhost:8000/docs
```

### 5. Generate an Article

```bash
# Async (returns job_id for polling):
curl -X POST http://localhost:8000/api/v1/articles/generate \
  -H "Content-Type: application/json" \
  -d '{"topic": "best productivity tools for remote teams", "target_word_count": 1500}'

# Sync (blocks until complete):
curl -X POST "http://localhost:8000/api/v1/articles/generate?sync=true" \
  -H "Content-Type: application/json" \
  -d '{"topic": "best productivity tools for remote teams"}'

# Check job status:
curl http://localhost:8000/api/v1/jobs/{job_id}

# Resume a failed job:
curl -X POST http://localhost:8000/api/v1/jobs/{job_id}/resume

# List all jobs:
curl http://localhost:8000/api/v1/jobs?status=completed
```

### Docker

```bash
docker build -t seo-agent .
docker run -p 8000:8000 --env-file .env seo-agent
```

## Quality Scoring Dimensions

| Dimension | Weight | What It Checks |
|-----------|--------|----------------|
| Keyword Presence | Equal | Primary keyword in title, intro, headings |
| Heading Structure | Equal | Single H1, 3+ H2s, no skipped levels |
| Word Count | Equal | Within 70-140% of target |
| Readability | Equal | Flesch Reading Ease 45-75 (web-optimized) |
| Content Depth | Equal | Number of H2+H3 sections |
| Meta Quality | Equal | Title tag 30-60 chars, meta desc 70-160 chars, keyword presence |

Articles scoring ≥6.0 overall with all dimensions passing are marked as quality-approved.

## Example Input → Output

See [`examples/sample_output.json`](examples/sample_output.json) for a complete example showing the request, generated article structure, SEO metadata, linking strategy, FAQ section, and quality report.
