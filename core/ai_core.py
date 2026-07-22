"""AI Core: pydantic-ai + Vertex AI Gemini + validation/reflection loop + circuit breaker.

Portfolio centerpiece — demonstrates:
1. Type-safe LLM output enforcement via Pydantic schemas
2. Reflection loop with error injection (self-healing)
3. Deterministic circuit breaker fallback (never stalls)
"""
import hashlib
import json
import os
from pydantic import BaseModel, field_validator, model_validator
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google_cloud import GoogleCloudProvider
from google.oauth2 import service_account
from core.config import GCP_PROJECT, GCP_REGION, GCP_CREDENTIALS
from core.database import get_conn

# --- Schemas ---

class MatchAnalysis(BaseModel):
    """Strict schema for LLM match analysis output."""
    match_id: int
    headline: str
    summary: str  # 2-3 sentences
    home_win: float
    draw: float
    away_win: float
    key_factors: list[str]  # max 5
    predicted_scoreline: str  # e.g. "2-1"
    confidence_level: str = "medium"  # low/medium/high — how strongly the model leans

    @field_validator("key_factors")
    @classmethod
    def limit_factors(cls, v):
        return v[:5]

    @model_validator(mode="after")
    def probabilities_sum_to_100(self):
        total = self.home_win + self.draw + self.away_win
        if abs(total - 100.0) > 0.5:
            raise ValueError(f"Probabilities sum to {total}, must equal 100.0")
        return self


class ArticleContent(BaseModel):
    """Schema for pSEO article generation."""
    title: str
    meta_description: str  # max 160 chars
    content: str  # markdown, 400-800 words
    slug: str

    @field_validator("meta_description")
    @classmethod
    def meta_length(cls, v):
        if len(v) > 160:
            return v[:157] + "..."
        return v


# --- Vertex AI Setup ---

def _get_model(flash: bool = True) -> GoogleModel:
    """Get Gemini model via Vertex AI with service account auth."""
    model_name = "gemini-2.5-flash" if flash else "gemini-2.5-pro"
    creds = service_account.Credentials.from_service_account_file(
        GCP_CREDENTIALS,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    provider = GoogleCloudProvider(
        credentials=creds,
        project=GCP_PROJECT,
        location=GCP_REGION,
    )
    return GoogleModel(model_name, provider=provider)


# --- Agents ---

analysis_agent = Agent(
    model=_get_model(flash=False),  # Pro for analysis
    output_type=MatchAnalysis,
    instructions=(
        "You are a football analytics expert. Given match data and Poisson predictions, "
        "produce a structured analysis. Probabilities MUST sum to exactly 100.0. "
        "Be concise, data-driven, no speculation beyond the numbers."
    ),
)

article_agent = Agent(
    model=_get_model(flash=True),  # Flash for bulk content
    output_type=ArticleContent,
    instructions=(
        "You are a sports journalist. Write a data-backed match preview/report. "
        "Include the Poisson probability table in the article. "
        "Be informational, NOT a betting tip. No gambling language. "
        "Write 400-800 words of unique analysis grounded in the provided statistics."
    ),
)


# --- Circuit Breaker ---

class CircuitBreaker:
    """Deterministic fallback after N consecutive LLM failures."""

    def __init__(self, max_failures: int = 3):
        self.max_failures = max_failures
        self.failures = 0

    def record_failure(self):
        self.failures += 1

    def record_success(self):
        self.failures = 0

    @property
    def is_open(self) -> bool:
        return self.failures >= self.max_failures

    def normalize_prediction(self, home_win: float, draw: float, away_win: float) -> dict:
        """Deterministic normalization — forces valid output without LLM."""
        total = home_win + draw + away_win
        if total == 0:
            return {"home_win": 33.3, "draw": 33.4, "away_win": 33.3}
        hw = round(home_win / total * 100, 1)
        d = round(draw / total * 100, 1)
        aw = round(100.0 - hw - d, 1)
        return {"home_win": hw, "draw": d, "away_win": aw}


_breaker = CircuitBreaker(max_failures=3)


# --- Validation/Reflection Loop ---

async def generate_analysis(match_id: int, context: str) -> MatchAnalysis | dict:
    """Run analysis with reflection loop. Falls back to circuit breaker on repeated failure."""
    if _breaker.is_open:
        # Deterministic fallback — parse Poisson numbers from context
        return {"error": "circuit_breaker_active", "match_id": match_id}

    last_error = None
    for attempt in range(3):
        try:
            prompt = context
            if last_error:
                prompt += f"\n\nPREVIOUS ERROR — FIX THIS: {last_error}"

            result = await analysis_agent.run(prompt)
            _breaker.record_success()
            return result.data
        except Exception as e:
            last_error = str(e)
            _breaker.record_failure()

    # All 3 attempts failed — circuit breaker now open
    return {"error": "validation_failed", "last_error": last_error, "match_id": match_id}


async def generate_article(match_id: int, context: str) -> ArticleContent | dict:
    """Generate pSEO article with content-hash caching."""
    # Content-hash cache — skip if same input already generated
    content_hash = hashlib.md5(context.encode()).hexdigest()
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM articles WHERE match_id=? AND content_hash=?",
        (match_id, content_hash),
    ).fetchone()
    conn.close()

    if existing:
        return {"cached": True, "article_id": existing["id"]}

    try:
        result = await article_agent.run(context)
        article = result.data
        # Store
        conn = get_conn()
        conn.execute(
            """INSERT INTO articles (match_id, slug, title, content, meta_description, content_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (match_id, article.slug, article.title, article.content,
             article.meta_description, content_hash),
        )
        conn.commit()
        conn.close()
        return article
    except Exception as e:
        return {"error": str(e), "match_id": match_id}
