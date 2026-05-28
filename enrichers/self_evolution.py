"""
Self-evolution engine — 3 layers:
  Layer 1: Few-shot injection (real-time, from feedback.jsonl)
  Layer 2: Blocklist/allowlist dynamic adjustment (weekly)
  Layer 3: Scoring prompt distillation (monthly, requires Gary confirmation)
"""
from __future__ import annotations
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import config

log = logging.getLogger(__name__)

FEEDBACK_DIR = config.DATA_DIR / "feedback"
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
EVOLUTION_DIR = config.DATA_DIR / "evolution"
EVOLUTION_DIR.mkdir(parents=True, exist_ok=True)


# ── LAYER 1: Few-shot loader ───────────────────────────────────────────────────

def load_few_shots(max_items: int = 4) -> list[dict]:
    """
    Load high-confidence feedback samples for S3 few-shot injection.
    Called by s3_scorer.run_s3() before each scoring run.
    """
    samples: list[dict] = []

    for fpath in sorted(FEEDBACK_DIR.glob("*.jsonl"), reverse=True)[:7]:
        try:
            for line in fpath.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                # Only high-confidence samples
                if item.get("action") in ("interested", "ignored", "watchlist"):
                    if item.get("score_override") or item.get("action") in ("interested", "ignored"):
                        samples.append(item)
        except Exception:
            continue

    # Prioritize: score_override samples > watchlist > interested > ignored
    def priority(s: dict) -> int:
        if s.get("score_override"):
            return 3
        if s.get("action") == "watchlist":
            return 2
        if s.get("action") == "interested":
            return 1
        return 0

    samples.sort(key=priority, reverse=True)
    return samples[:max_items]


def save_feedback(
    item_id: str,
    title: str,
    action: str,           # interested|ignored|watchlist|follow_up
    score: float = 0,      # actual score (used by web UI)
    track: str = "",
    note: str = "",        # Gary's free-text note
    score_override: int = 0,
    score_reason: str = "",
    dim_flag: str = "",    # "ai_native:high" etc.
    category_override: str = "",
) -> None:
    """Save a Gary feedback event to feedback.jsonl."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fpath = FEEDBACK_DIR / f"{date_str}.jsonl"

    record = {
        "item_id": item_id,
        "title": title,
        "action": action,
        "track": track,
        "score": score,
        "note": note,
        "score_override": score_override,
        "score_reason": score_reason,
        "dim_flag": dim_flag,
        "category_override": category_override,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    with fpath.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    log.info("[evolution] feedback saved: %s → %s", title[:40], action)

    # Trigger Layer 2 check after every 3 new feedbacks
    _check_layer2_trigger()


# ── LAYER 2: Blocklist/allowlist dynamic adjustment ───────────────────────────

LAYER2_TRACKER = EVOLUTION_DIR / "pattern_tracker.json"
LAYER2_TRIGGER_COUNT = 3   # consecutive same-type actions to trigger adjustment


def _check_layer2_trigger() -> None:
    """Check if recent feedback patterns warrant blocklist adjustment."""
    all_feedback = _load_all_feedback()
    if len(all_feedback) < 10:
        return

    recent = all_feedback[-20:]   # last 20 feedback items

    # Count ignored patterns
    ignored = [f for f in recent if f.get("action") == "ignored"]
    if len(ignored) >= 3:
        _analyze_ignored_patterns(ignored)


def _analyze_ignored_patterns(ignored: list[dict]) -> None:
    """Look for systematic patterns in ignored items."""
    tracker_path = LAYER2_TRACKER
    tracker = {}
    if tracker_path.exists():
        try:
            tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Extract titles for pattern analysis
    titles = [f.get("title", "").lower() for f in ignored]
    words = []
    for title in titles:
        words.extend(title.split())

    word_freq = Counter(words)
    high_freq = [(w, c) for w, c in word_freq.items()
                 if c >= 3 and len(w) > 4 and w not in ("with", "from", "that", "this")]

    if high_freq:
        tracker["suggested_blocklist_additions"] = [w for w, _ in high_freq[:5]]
        tracker["last_analyzed"] = datetime.now(timezone.utc).isoformat()
        tracker_path.write_text(json.dumps(tracker, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("[evolution:L2] pattern tracker updated: %s", [w for w, _ in high_freq[:5]])


def _load_all_feedback() -> list[dict]:
    all_items = []
    for fpath in sorted(FEEDBACK_DIR.glob("*.jsonl")):
        for line in fpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                all_items.append(json.loads(line))
            except Exception:
                pass
    return all_items


def get_dynamic_blocklist() -> set[str]:
    """Return current dynamic blocklist for S1 use."""
    tracker_path = LAYER2_TRACKER
    if not tracker_path.exists():
        return set()
    try:
        tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
        return set(tracker.get("active_blocklist", []))
    except Exception:
        return set()


# ── LAYER 3: Scoring prompt distillation (monthly) ───────────────────────────

def generate_distillation_report() -> Path:
    """
    Analyze all feedback to surface systematic scoring errors.
    Generates scoring_notes.md for Gary's review.
    Must be manually confirmed before updating scoring prompt.
    """
    all_feedback = _load_all_feedback()
    if len(all_feedback) < 20:
        log.info("[evolution:L3] not enough feedback (%d < 20), skipping", len(all_feedback))
        return EVOLUTION_DIR / "scoring_notes.md"

    # Summarize patterns
    overrides = [f for f in all_feedback if f.get("score_override", 0) > 0]
    interested_ignored = [(f["title"], f["action"]) for f in all_feedback
                          if f.get("action") in ("interested", "ignored")]

    summary_lines = [
        f"# Scoring Distillation Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        f"Total feedback: {len(all_feedback)}",
        f"Score overrides: {len(overrides)}",
        "",
        "## Score Overrides (Gary corrected system score)",
    ]

    for ov in overrides[:10]:
        summary_lines.append(
            f"- **{ov.get('title','')}**: override={ov.get('score_override')} | reason: {ov.get('score_reason','')}"
        )

    summary_lines += [
        "",
        "## Patterns in Ignored Items",
        "(Review for potential blocklist additions)",
        "",
    ]
    
    ignored = [f for f in all_feedback if f.get("action") == "ignored"]
    if ignored:
        for ig in ignored[:10]:
            summary_lines.append(f"- {ig.get('title','')} (track:{ig.get('track','')})")

    summary_lines += [
        "",
        "## Action Items for Gary",
        "[ ] Review score overrides — do they suggest systematic bias?",
        "[ ] Review ignored patterns — any keywords to add to S1 blocklist?",
        "[ ] Confirm any scoring_notes below before applying to scoring.py",
        "",
        "## Suggested Scoring Notes (pending confirmation)",
        "_Fill in after reviewing the above_",
    ]

    report_path = EVOLUTION_DIR / "scoring_notes.md"
    report_path.write_text("\n".join(summary_lines), encoding="utf-8")
    log.info("[evolution:L3] distillation report generated: %s", report_path)
    return report_path
