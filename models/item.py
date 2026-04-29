"""
Unified data model for all signal sources.
Every collector outputs a list of SignalItem — no source-specific structs.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SignalItem:
    # ── Identity ──────────────────────────────────────────────────────────────
    id: str                          # stable hash of (source, url)
    source: str                      # "producthunt" | "github" | "hackernews" |
                                     # "openrouter" | "x_twitter" | "reddit" |
                                     # "huggingface" | "github_events"
    collected_at: str                # ISO-8601 UTC

    # ── Core content ──────────────────────────────────────────────────────────
    title: str
    url: str
    description_en: str = ""
    description_zh: str = ""         # filled by LLM enricher
    keywords: list[str] = field(default_factory=list)
    score: float = 0.0               # 0-10, filled by LLM enricher

    # ── Source-specific metrics (raw, kept for display & analytics) ────────────
    metrics: dict[str, Any] = field(default_factory=dict)
    # Examples by source:
    # producthunt:  {"upvotes": 312, "comments": 45, "makers": ["@alice"]}
    # github:       {"stars": 8400, "stars_today": 620, "forks": 340, "language": "Python"}
    # github_events:{"stars_before": 12, "stars_after": 780, "delta": 768, "hours": 24}
    # hackernews:   {"score": 312, "comments": 87, "hn_id": "40123456"}
    # openrouter:   {"tokens_week": "103B", "wow_pct": 101, "rank": 11, "categories": ["coding"]}
    # x_twitter:    {"likes": 2400, "retweets": 580, "bookmarks": 340, "impressions": 48000}
    # reddit:       {"upvotes": 1840, "comments": 234, "subreddit": "LocalLLaMA"}
    # huggingface:  {"downloads_month": 450000, "likes": 1200, "type": "model"}

    # ── Growth signal ─────────────────────────────────────────────────────────
    is_new: bool = False             # first time seen in any run
    is_trending: bool = False        # flagged as fast-growing by source itself
    wow_growth_pct: Optional[float] = None   # week-over-week % if computable

    # ── Media ─────────────────────────────────────────────────────────────────
    thumbnail_url: Optional[str] = None
    has_video: bool = False          # for X: launch demo videos

    # ── Raw ───────────────────────────────────────────────────────────────────
    raw: dict[str, Any] = field(default_factory=dict)


def make_id(source: str, url: str) -> str:
    key = f"{source}::{url.rstrip('/').lower()}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]
