"""
Central config — all credentials read from environment / .env.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    pass


# ── LLM (OpenRouter, OpenAI-compatible) ──────────────────────────────────────
LLM_API_KEY: str = os.getenv("OPENROUTER_API_KEY", os.getenv("OPENAI_API_KEY", ""))
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL: str = os.getenv("LLM_MODEL", "google/gemini-flash-1.5")          # cheap + fast
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "60"))

# ── X / Twitter ──────────────────────────────────────────────────────────────
X_API_KEY: str = os.getenv("X_API_KEY", "")
X_API_SECRET: str = os.getenv("X_API_SECRET", "")
X_ACCESS_TOKEN: str = os.getenv("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET: str = os.getenv("X_ACCESS_TOKEN_SECRET", "")

# ── Product Hunt ─────────────────────────────────────────────────────────────
PH_TOKEN: str = os.getenv("PRODUCTHUNT_DEVELOPER_TOKEN", os.getenv("PRODUCTHUNT_API_KEY", ""))

# ── GitHub ────────────────────────────────────────────────────────────────────
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", os.getenv("GH_TOKEN", ""))

# ── Reddit ────────────────────────────────────────────────────────────────────
REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "CreekstoneRadar/2.0")

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
STRUCTURED_DIR = DATA_DIR / "structured"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
REPORTS_DIR = DATA_DIR / "reports"

for _d in (RAW_DIR, STRUCTURED_DIR, SNAPSHOTS_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Collector switches ────────────────────────────────────────────────────────
ENABLED_SOURCES: list[str] = [
    s.strip()
    for s in os.getenv(
        "ENABLED_SOURCES",
        "producthunt,github_trending,github_events,hackernews,openrouter,huggingface,x_twitter,reddit"
    ).split(",")
    if s.strip()
]

# ── Thresholds ────────────────────────────────────────────────────────────────
GITHUB_STARS_SPIKE_THRESHOLD: int = int(os.getenv("GITHUB_STARS_SPIKE_THRESHOLD", "200"))
OPENROUTER_WOW_THRESHOLD: int = int(os.getenv("OPENROUTER_WOW_THRESHOLD", "50"))   # %
X_MIN_LIKES: int = int(os.getenv("X_MIN_LIKES", "20"))
X_MAX_RESULTS: int = int(os.getenv("X_MAX_RESULTS", "50"))
REDDIT_MIN_UPVOTES: int = int(os.getenv("REDDIT_MIN_UPVOTES", "30"))
