"""
SignalItem v2 — unified data model for all sources.
New fields: track, fde_index, traffic_data, team_info, feedback_state.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal, Optional
import hashlib

Track = Literal["A", "B", "C", "unknown"]
FeedbackState = Literal["interested", "ignored", "watchlist", "pending"]


@dataclass
class TeamInfo:
    founders: list[str] = field(default_factory=list)   # ["Alice Wang (ex-Stripe)"]
    company_size: str = ""                                # "5-10"
    founded_year: Optional[int] = None
    location: str = ""
    linkedin_urls: list[str] = field(default_factory=list)
    is_chinese_heritage: bool = False
    notes: str = ""                                       # LLM-extracted summary


@dataclass
class TrafficData:
    domain: str = ""
    total_visits: int = 0
    mom_growth_pct: float = 0.0      # month-over-month %
    snapshot_date: str = ""          # "2026-05"
    traffic_spike: bool = False      # MoM > 40%
    is_new_product: bool = False     # first time tracked


@dataclass
class ScoreBreakdown:
    ai_native: int = 0      # 0-30
    niche: int = 0          # 0-25
    business: int = 0       # 0-20
    team: int = 0           # 0-15
    bonus: int = 0          # 0-10
    penalty: int = 0        # 0-10
    total: int = 0
    reason: str = ""
    plus: list[str] = field(default_factory=list)
    minus: list[str] = field(default_factory=list)


@dataclass
class SignalItem:
    # ── Identity ──────────────────────────────────────────────────────────────
    id: str
    source: str           # producthunt|github_trending|github_events|arxiv|
                          # hackernews|discord|reddit|x_twitter|
                          # openrouter|huggingface|similarweb
    collected_at: str     # ISO-8601 UTC

    # ── Core content ──────────────────────────────────────────────────────────
    title: str
    url: str
    description_en: str = ""
    description_zh: str = ""
    keywords: list[str] = field(default_factory=list)

    # ── Investment classification (new in v2) ─────────────────────────────────
    track: Track = "unknown"
    track_reason: str = ""          # S2 one-line reason
    track_confidence: str = "low"   # high|medium|low
    fde_index: int = 0              # 0-10, Track B only
    fde_stage: str = ""             # "single_tool"|"accumulating"|"flywheel"|"achieved"

    # ── Scoring ───────────────────────────────────────────────────────────────
    score: float = 0.0
    score_breakdown: Optional[ScoreBreakdown] = None

    # ── Enrichment ────────────────────────────────────────────────────────────
    team: Optional[TeamInfo] = None
    traffic: Optional[TrafficData] = None

    # ── Signal flags ──────────────────────────────────────────────────────────
    is_new: bool = False
    is_trending: bool = False
    is_spike: bool = False          # sudden traffic/usage spike
    wow_growth_pct: Optional[float] = None
    has_video: bool = False

    # ── Human feedback ────────────────────────────────────────────────────────
    feedback_state: FeedbackState = "pending"

    # ── Source metrics (raw) ──────────────────────────────────────────────────
    metrics: dict[str, Any] = field(default_factory=dict)
    thumbnail_url: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


def make_id(source: str, url: str) -> str:
    key = f"{source}::{url.rstrip('/').lower()}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def extract_domain(url: str) -> str:
    """Extract base domain for cross-source dedup."""
    import re
    m = re.search(r"(?:https?://)?(?:www\.)?([^/\s?#]+)", url.lower())
    return m.group(1) if m else ""
