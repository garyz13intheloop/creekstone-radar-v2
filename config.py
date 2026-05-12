"""Central config — all credentials from environment / .env"""
from __future__ import annotations
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    pass

# ── LLM ──────────────────────────────────────────────────────────────────────
LLM_API_KEY: str = os.getenv("OPENROUTER_API_KEY", os.getenv("OPENAI_API_KEY", ""))
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL: str = os.getenv("LLM_MODEL", "google/gemini-2.0-flash-001")   # S2: cheap fast
S3_MODEL: str = os.getenv("S3_MODEL", "google/gemini-2.0-flash-001")       # S3: can upgrade to claude-haiku
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "60"))

# ── X / Twitter ──────────────────────────────────────────────────────────────
X_API_KEY: str = os.getenv("X_API_KEY", "")
X_API_SECRET: str = os.getenv("X_API_SECRET", "")
X_ACCESS_TOKEN: str = os.getenv("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET: str = os.getenv("X_ACCESS_TOKEN_SECRET", "")

# ── Product Hunt ─────────────────────────────────────────────────────────────
PH_TOKEN: str = os.getenv("PRODUCTHUNT_DEVELOPER_TOKEN", os.getenv("PRODUCTHUNT_API_KEY", ""))

# ── GitHub ────────────────────────────────────────────────────────────────────
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", os.getenv("GH_PAT", ""))

# ── Reddit ────────────────────────────────────────────────────────────────────
REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "CreekstoneRadar/2.0")

# ── Discord ───────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")

# ── Feishu ────────────────────────────────────────────────────────────────────
FEISHU_WEBHOOK_URL: str = os.getenv("FEISHU_WEBHOOK_URL", "")

# ── Similarweb ────────────────────────────────────────────────────────────────
SCRAPE_DO_TOKEN: str = os.getenv("SCRAPE_DO_TOKEN", "")

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
STRUCTURED_DIR = DATA_DIR / "structured"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
REPORTS_DIR = DATA_DIR / "reports"
TRAFFIC_DIR = DATA_DIR / "traffic"
FEEDBACK_DIR = DATA_DIR / "feedback"
EVOLUTION_DIR = DATA_DIR / "evolution"

for _d in (STRUCTURED_DIR, SNAPSHOTS_DIR, REPORTS_DIR, TRAFFIC_DIR, FEEDBACK_DIR, EVOLUTION_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Source switches ───────────────────────────────────────────────────────────
ENABLED_SOURCES: list[str] = [
    s.strip()
    for s in os.getenv(
        "ENABLED_SOURCES",
        "producthunt,github_trending,github_events,arxiv,hackernews,discord,reddit,x_twitter,openrouter,huggingface"
    ).split(",")
    if s.strip()
]

# ── Thresholds ────────────────────────────────────────────────────────────────
GITHUB_STARS_SPIKE_THRESHOLD: int = int(os.getenv("GITHUB_STARS_SPIKE_THRESHOLD", "200"))
OPENROUTER_WOW_THRESHOLD: int = int(os.getenv("OPENROUTER_WOW_THRESHOLD", "50"))
X_MIN_LIKES: int = int(os.getenv("X_MIN_LIKES", "20"))
X_MAX_RESULTS: int = int(os.getenv("X_MAX_RESULTS", "50"))
REDDIT_MIN_UPVOTES: int = int(os.getenv("REDDIT_MIN_UPVOTES", "30"))
