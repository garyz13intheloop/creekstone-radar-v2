"""
历史数据迁移脚本 v3
1. 从 creekstone-daily-feeds 的 items.ndjson（5822条）迁移
2. 从 creekstone-radar-v2 旧格式 NDJSON 迁移（无 track/full_profile 的旧数据）
3. 全部重新跑 S2 Track 分类 + S3 评分（新格式）
4. 写入 radar-v2 的 data/structured/ 对应日期文件

Usage:
  python pipeline/migrate_history.py --source daily-feeds [--days 30] [--skip-scored]
  python pipeline/migrate_history.py --source radar-v2-old [--days 30]
  python pipeline/migrate_history.py --source both [--days 30]
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from models.item import SignalItem, ScoreBreakdown, FullProfile, make_id
from pipeline.s2_router import run_s2
from pipeline.s3_scorer import run_s3
from storage.store import save_daily
from enrichers.self_evolution import load_few_shots

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

DAILY_FEEDS_ROOT = Path.home() / "creekstone-daily-feeds"


# ── Converters ────────────────────────────────────────────────────────────────

def _from_daily_feeds_item(d: dict) -> SignalItem | None:
    """Convert daily-feeds NDJSON item to SignalItem."""
    title = d.get("title", "").strip()
    url = d.get("url", "").strip()
    if not title or not url:
        return None

    source_raw = d.get("source", "")
    # Map source names
    source_map = {
        "producthunt": "producthunt",
        "github": "github_trending",
        "arxiv": "arxiv",
        "clawhub": "clawhub",   # will be filtered out later
    }
    source = source_map.get(source_raw, source_raw)
    if source == "clawhub":
        return None  # skip clawhub

    date_str = d.get("date", "")
    collected_at = f"{date_str}T09:00:00Z" if date_str else datetime.now(timezone.utc).isoformat()

    # Extract metrics
    raw_metrics = d.get("metrics", {}) or {}
    if isinstance(raw_metrics, str):
        try:
            raw_metrics = json.loads(raw_metrics)
        except Exception:
            raw_metrics = {}

    # Extract score from old format: {"breakdown": {...}, "total": 75}
    old_score = d.get("score", {})
    score_total = 0
    if isinstance(old_score, dict):
        score_total = old_score.get("total", 0) or 0
    elif isinstance(old_score, (int, float)):
        score_total = float(old_score)

    item = SignalItem(
        id=make_id(source, url),
        source=source,
        collected_at=collected_at,
        title=title,
        url=url,
        description_en=(d.get("description_en") or "")[:1000],
        description_zh=(d.get("description_zh") or "")[:500],
        keywords=d.get("keywords") or [],
        is_new=(d.get("ai_flags") or {}).get("is_new", False) if isinstance(d.get("ai_flags"), dict) else False,
        is_trending=(d.get("ai_flags") or {}).get("is_trending", False) if isinstance(d.get("ai_flags"), dict) else False,
        metrics=raw_metrics,
        thumbnail_url=(d.get("media", {}) or {}).get("thumbnail") if isinstance(d.get("media"), dict) else None,
    )
    # Keep old score if it was valid (non-zero, non-error)
    if score_total > 10:
        item.score = float(score_total)

    return item


def _from_radar_v2_old(d: dict) -> SignalItem | None:
    """Convert old radar-v2 NDJSON (no track/full_profile) to SignalItem."""
    title = d.get("title", "").strip()
    url = d.get("url", "").strip()
    if not title or not url:
        return None
    # Already has track? Skip (already migrated)
    if d.get("track") and d.get("track") != "unknown" and d.get("full_profile"):
        return None

    item = SignalItem(
        id=d.get("id") or make_id(d.get("source", ""), url),
        source=d.get("source", ""),
        collected_at=d.get("collected_at", ""),
        title=title,
        url=url,
        description_en=d.get("description_en", ""),
        description_zh=d.get("description_zh", ""),
        keywords=d.get("keywords", []),
        score=float(d.get("score", 0)),
        is_new=d.get("is_new", False),
        is_trending=d.get("is_trending", False),
        wow_growth_pct=d.get("wow_growth_pct"),
        has_video=d.get("has_video", False),
        metrics=d.get("metrics", {}),
        thumbnail_url=d.get("thumbnail_url"),
    )
    return item


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_daily_feeds_items(days: int) -> dict[str, list[SignalItem]]:
    """Load daily-feeds items, grouped by date."""
    ndjson_path = DAILY_FEEDS_ROOT / "data/structured/items.ndjson"
    if not ndjson_path.exists():
        log.warning("daily-feeds items.ndjson not found at %s", ndjson_path)
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    by_date: dict[str, list[SignalItem]] = {}
    skipped = 0

    with ndjson_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                date_str = d.get("date", "")
                if not date_str:
                    continue
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
                item = _from_daily_feeds_item(d)
                if item:
                    by_date.setdefault(date_str, []).append(item)
                else:
                    skipped += 1
            except Exception as e:
                skipped += 1

    total = sum(len(v) for v in by_date.values())
    log.info("[migrate] daily-feeds: %d items across %d dates (skipped %d)", total, len(by_date), skipped)
    return by_date


def load_radar_v2_old_items(days: int) -> dict[str, list[SignalItem]]:
    """Load old radar-v2 ndjson files that lack track/full_profile."""
    structured = ROOT / "data/structured"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    by_date: dict[str, list[SignalItem]] = {}

    for fpath in sorted(structured.glob("*.ndjson")):
        date_str = fpath.stem
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt < cutoff:
            continue

        items: list[SignalItem] = []
        for line in fpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                # Skip if already has full new format
                if d.get("track") and d.get("track") != "unknown" and d.get("full_profile"):
                    continue
                item = _from_radar_v2_old(d)
                if item:
                    items.append(item)
            except Exception:
                pass

        if items:
            by_date[date_str] = items
            log.info("[migrate] radar-v2-old %s: %d items to re-process", date_str, len(items))

    return by_date


# ── Main migrate flow ─────────────────────────────────────────────────────────

def migrate(source: str, days: int, skip_s2: bool = False, skip_s3: bool = False,
            batch_size: int = 30) -> None:
    """Full migration: load → S2 → S3 → save."""

    # Load
    if source == "daily-feeds":
        by_date = load_daily_feeds_items(days)
    elif source == "radar-v2-old":
        by_date = load_radar_v2_old_items(days)
    elif source == "both":
        by_date = load_daily_feeds_items(days)
        old = load_radar_v2_old_items(days)
        for date_str, items in old.items():
            by_date.setdefault(date_str, []).extend(items)
    else:
        raise ValueError(f"Unknown source: {source}")

    if not by_date:
        log.info("[migrate] No items to migrate.")
        return

    total_dates = len(by_date)
    total_items = sum(len(v) for v in by_date.values())
    log.info("[migrate] Starting: %d dates, %d items total", total_dates, total_items)

    few_shots = load_few_shots() if not skip_s3 else []
    processed = 0

    for date_idx, (date_str, items) in enumerate(sorted(by_date.items())):
        log.info("[migrate] %s (%d/%d): %d items", date_str, date_idx + 1, total_dates, len(items))

        # Deduplicate within batch by ID
        seen_ids: set[str] = set()
        deduped = []
        for item in items:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                deduped.append(item)

        # Process in batches to avoid memory issues
        for batch_start in range(0, len(deduped), batch_size):
            batch = deduped[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1

            # S2: Track classification
            if not skip_s2 and config.LLM_API_KEY:
                # Only run S2 on items without a valid track
                needs_s2 = [i for i in batch if not i.track or i.track == "unknown"]
                has_track = [i for i in batch if i.track and i.track != "unknown"]
                if needs_s2:
                    s2_passed, _ = run_s2(needs_s2)
                    batch = has_track + s2_passed
                    time.sleep(0.5)

            # S3: Scoring — only re-score items with score == 0 or track has changed
            if not skip_s3 and config.LLM_API_KEY:
                needs_s3 = [i for i in batch if i.score < 10]  # re-score low/zero scored
                has_score = [i for i in batch if i.score >= 10]
                if needs_s3:
                    scored = run_s3(needs_s3, few_shot_loader=lambda: few_shots)
                    batch = has_score + scored
                    time.sleep(0.5)

            # Save
            save_daily(batch, date_str)
            processed += len(batch)
            log.info("[migrate] %s batch %d: saved %d items (total processed: %d)",
                     date_str, batch_num, len(batch), processed)

    log.info("[migrate] Done. Processed %d items across %d dates.", processed, total_dates)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Creekstone history migration")
    parser.add_argument("--source", choices=["daily-feeds", "radar-v2-old", "both"], default="both")
    parser.add_argument("--days", type=int, default=30, help="How many days back to migrate")
    parser.add_argument("--no-s2", action="store_true", help="Skip track classification")
    parser.add_argument("--no-s3", action="store_true", help="Skip scoring")
    parser.add_argument("--batch-size", type=int, default=20, help="Items per S3 batch")
    args = parser.parse_args()

    migrate(
        source=args.source,
        days=args.days,
        skip_s2=args.no_s2,
        skip_s3=args.no_s3,
        batch_size=args.batch_size,
    )
