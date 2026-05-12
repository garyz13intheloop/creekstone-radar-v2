"""
S1 — Hard rule filter. Zero LLM cost. Runs on every raw item.
Handles per-source thresholds, blocklists, allowlists, and fast-pass flags.
"""
from __future__ import annotations
import re
import logging
from models.item import SignalItem

log = logging.getLogger(__name__)

# ── Blocklist ─────────────────────────────────────────────────────────────────
DOMAIN_BLOCKLIST = {
    # Topic noise
    "crypto", "nft", "blockchain", "web3", "casino", "gambling",
    "betting", "porn", "adult", "dating",
    # News agencies that spam agent/AI in political context
    "aninews", "apnews", "reuters", "bbc", "cnn", "foxnews",
}

KEYWORD_BLOCKLIST = {
    "election", "politician", "polling", "vote for", "booth agent",
    "sports agent", "talent agent", "real estate agent listing",
    "insurance agent quote",
}

# ── Allowlist (must hit at least one) ─────────────────────────────────────────
AI_AGENT_SIGNALS = {
    # Core agent terms
    "agent", "agentic", "autonomous", "multi-agent", "subagent",
    # Infrastructure
    "mcp", "tool use", "tool-use", "function call", "orchestrat",
    "workflow", "pipeline", "rag", "retrieval", "embedding",
    # Model layer
    "llm", "gpt", "claude", "gemini", "mistral", "qwen",
    "fine-tun", "inference", "prompt", "context window",
    # Modalities
    "multimodal", "vision model", "audio model", "diffusion",
    # Product signals
    "copilot", "assistant", "chatbot", "coding agent",
    "vibe coding", "ai coding", "ai-native",
    # Track C
    "a2a", "agent network", "agent protocol", "agent marketplace",
    "robot", "physical ai",
}

# ── Per-source minimum thresholds ─────────────────────────────────────────────
SOURCE_THRESHOLDS: dict[str, dict] = {
    "producthunt":     {"votes": 10},
    "github_trending": {"stars_today": 20},
    "github_events":   {"stars_per_day": 15},
    "arxiv":           {},   # all papers pass (already filtered by category)
    "hackernews":      {"points": 10},
    "discord":         {},   # all pass (already filtered at collection)
    "reddit":          {"upvotes": 30},
    "x_twitter":       {"likes": 20},
    "openrouter":      {"tokens_int": 1_000_000_000},  # 1B tokens
    "huggingface":     {"likes": 20},
}

# ── Fast-pass conditions (bypass threshold check) ─────────────────────────────
def _is_fast_pass(item: SignalItem) -> bool:
    """Items that skip S1 thresholds entirely."""
    if item.has_video:                                      # X demo video
        return True
    if item.source == "openrouter" and item.is_trending:   # OR trending section
        return True
    if item.is_new and item.source == "github_events":     # brand-new star spike
        spd = item.metrics.get("stars_per_day", 0)
        if spd >= 50:
            return True
    wow = item.wow_growth_pct or 0
    if wow >= 200:                                          # massive WoW growth
        return True
    return False


def _meets_threshold(item: SignalItem) -> bool:
    thresholds = SOURCE_THRESHOLDS.get(item.source, {})
    m = item.metrics
    for field, min_val in thresholds.items():
        actual = m.get(field, 0)
        try:
            if float(actual) < float(min_val):
                return False
        except (TypeError, ValueError):
            pass
    return True


def _has_ai_signal(item: SignalItem) -> bool:
    text = f"{item.title} {item.description_en}".lower()
    return any(sig in text for sig in AI_AGENT_SIGNALS)


def _is_blocked(item: SignalItem) -> bool:
    text = f"{item.title} {item.description_en} {item.url}".lower()
    # Domain blocklist
    for blocked in DOMAIN_BLOCKLIST:
        if blocked in text:
            return True
    # Keyword blocklist (only if NOT a strong AI signal present)
    if not _has_ai_signal(item):
        for blocked_kw in KEYWORD_BLOCKLIST:
            if blocked_kw in text:
                return True
    return False


def run_s1(items: list[SignalItem]) -> tuple[list[SignalItem], int]:
    """
    Returns (passed_items, dropped_count).
    """
    passed: list[SignalItem] = []
    dropped = 0

    for item in items:
        # 1. Block check (always applies)
        if _is_blocked(item):
            dropped += 1
            continue

        # 2. Fast-pass (skip threshold for high-signal items)
        if _is_fast_pass(item):
            passed.append(item)
            continue

        # 3. Must have AI/Agent signal
        if not _has_ai_signal(item):
            dropped += 1
            continue

        # 4. Per-source threshold
        if not _meets_threshold(item):
            dropped += 1
            continue

        passed.append(item)

    log.info("[S1] %d → %d (dropped %d)", len(items), len(passed), dropped)
    return passed, dropped
