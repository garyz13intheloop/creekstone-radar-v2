"""
全量历史数据重处理脚本
把所有旧格式 NDJSON（无 track/full_profile）用新的 S2+S3 重跑，写回原文件。
- 已有新格式的条目跳过（不重复消耗）
- 旧格式条目全部重跑
- 并发 S3（concurrency=5），约 10-12 条/分钟
- 断点续跑：已写入的直接跳过

Usage:
    python pipeline/reprocess_all.py [--date 2026-04-01] [--days-back 90] [--dry-run]
    python pipeline/reprocess_all.py --all   # 全量
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
from models.item import SignalItem, ScoreBreakdown, make_id
from pipeline.s2_router import run_s2
from pipeline.s3_scorer import run_s3
from pipeline.enricher_web import enrich_descriptions
from enrichers.self_evolution import load_few_shots
from storage.store import build_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/reprocess_all.log"),
    ],
)
log = logging.getLogger(__name__)

STRUCTURED = ROOT / "data" / "structured"


def load_ndjson(path: Path) -> list[dict]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                items.append(json.loads(line))
            except Exception:
                pass
    return items


def save_ndjson(path: Path, items: list[dict]):
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def is_new_format(d: dict) -> bool:
    """已经跑过新格式：有 track（非unknown）且有 full_profile 且 score > 0"""
    return (
        d.get("track") and d.get("track") not in ("unknown", "", None)
        and bool(d.get("full_profile"))
        and float(d.get("score", 0)) > 0
    )


def dict_to_signal_item(d: dict) -> SignalItem:
    return SignalItem(
        id=d.get("id") or make_id(d.get("source", ""), d.get("url", "")),
        source=d.get("source", ""),
        collected_at=d.get("collected_at", ""),
        title=d.get("title", ""),
        url=d.get("url", ""),
        description_en=d.get("description_en", ""),
        description_zh=d.get("description_zh", ""),
        keywords=d.get("keywords", []),
        track=d.get("track", "unknown"),
        track_reason=d.get("track_reason", ""),
        track_confidence=d.get("track_confidence", "low"),
        fde_index=d.get("fde_index", 0),
        fde_stage=d.get("fde_stage", ""),
        score=float(d.get("score", 0)),
        is_new=d.get("is_new", False),
        is_trending=d.get("is_trending", False),
        is_spike=d.get("is_spike", False),
        wow_growth_pct=d.get("wow_growth_pct"),
        has_video=d.get("has_video", False),
        feedback_state=d.get("feedback_state", "pending"),
        feedback_note=d.get("feedback_note", ""),
        sourcing_synced=d.get("sourcing_synced", False),
        metrics=d.get("metrics", {}),
        thumbnail_url=d.get("thumbnail_url"),
    )


def signal_item_to_dict(item: SignalItem) -> dict:
    """Full serialization including full_profile and score_breakdown."""
    import dataclasses
    def dc2d(obj):
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return {k: dc2d(v) for k, v in dataclasses.asdict(obj).items()}
        if isinstance(obj, list):
            return [dc2d(x) for x in obj]
        return obj

    d = {
        "id": item.id, "source": item.source, "collected_at": item.collected_at,
        "title": item.title, "url": item.url,
        "description_en": item.description_en, "description_zh": item.description_zh,
        "keywords": item.keywords,
        "track": item.track, "track_reason": item.track_reason,
        "track_confidence": item.track_confidence,
        "fde_index": item.fde_index, "fde_stage": item.fde_stage,
        "score": item.score,
        "is_new": item.is_new, "is_trending": item.is_trending,
        "is_spike": item.is_spike, "wow_growth_pct": item.wow_growth_pct,
        "has_video": item.has_video,
        "feedback_state": item.feedback_state, "feedback_note": item.feedback_note,
        "sourcing_synced": item.sourcing_synced,
        "metrics": item.metrics, "thumbnail_url": item.thumbnail_url,
    }
    if item.score_breakdown:
        d["score_breakdown"] = dc2d(item.score_breakdown)
    if item.full_profile:
        d["full_profile"] = dc2d(item.full_profile)
    if item.team:
        d["team"] = dc2d(item.team)
    return d


def reprocess_date(date_str: str, few_shots: list, dry_run: bool = False, no_web_fetch: bool = False) -> tuple[int, int]:
    """
    Reprocess one date file.
    Returns (reprocessed_count, skipped_count).
    """
    path = STRUCTURED / f"{date_str}.ndjson"
    if not path.exists():
        return 0, 0

    all_dicts = load_ndjson(path)
    if not all_dicts:
        return 0, 0

    # Split: already-done vs needs-reprocessing
    done_dicts = [d for d in all_dicts if is_new_format(d)]
    todo_dicts = [d for d in all_dicts if not is_new_format(d)]

    if not todo_dicts:
        log.info("[%s] all %d items already new-format, skipping", date_str, len(done_dicts))
        return 0, len(done_dicts)

    log.info("[%s] %d to reprocess, %d already done", date_str, len(todo_dicts), len(done_dicts))

    if dry_run:
        return len(todo_dicts), len(done_dicts)

    # Convert to SignalItems
    todo_items = [dict_to_signal_item(d) for d in todo_dicts]

    # Web enrich (fill thin descriptions)
    if not no_web_fetch:
        todo_items = enrich_descriptions(todo_items)

    # S2: Track classification (only for items without valid track)
    needs_s2 = [i for i in todo_items if not i.track or i.track in ("unknown", "")]
    has_track = [i for i in todo_items if i.track and i.track not in ("unknown", "")]
    if needs_s2 and config.LLM_API_KEY:
        s2_passed, _ = run_s2(needs_s2)
        todo_items = has_track + s2_passed
    
    # S3: Full scoring + profiling
    if config.LLM_API_KEY:
        todo_items = run_s3(todo_items, few_shot_loader=lambda: few_shots, concurrency=5)

    # Merge back: done_dicts (unchanged) + newly processed
    new_dicts = [signal_item_to_dict(i) for i in todo_items]
    
    # Dedup by ID, new format wins over old
    id_to_dict: dict[str, dict] = {}
    for d in done_dicts:
        id_to_dict[d["id"]] = d
    for d in new_dicts:
        id_to_dict[d["id"]] = d  # overwrite old with new

    merged = list(id_to_dict.values())
    # Sort by score desc
    merged.sort(key=lambda x: float(x.get("score", 0)), reverse=True)

    save_ndjson(path, merged)
    log.info("[%s] saved %d items (%d reprocessed, %d kept)", date_str, len(merged), len(new_dicts), len(done_dicts))
    return len(new_dicts), len(done_dicts)


def get_dates_to_process(days_back: int | None, specific_date: str | None, all_dates: bool) -> list[str]:
    if specific_date:
        return [specific_date]
    
    files = sorted(STRUCTURED.glob("*.ndjson"))
    all_file_dates = [f.stem for f in files if not f.stem.endswith(".old")]
    
    if all_dates:
        return all_file_dates
    
    if days_back:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        return [d for d in all_file_dates if d >= cutoff]
    
    # Default: only dates that need reprocessing
    needs = []
    for d in all_file_dates:
        path = STRUCTURED / f"{d}.ndjson"
        dicts = load_ndjson(path)
        if any(not is_new_format(item) for item in dicts):
            needs.append(d)
    return needs


def main():
    parser = argparse.ArgumentParser(description="Reprocess historical radar data")
    parser.add_argument("--date", help="Process single date YYYY-MM-DD")
    parser.add_argument("--days-back", type=int, help="Process last N days")
    parser.add_argument("--all", action="store_true", help="Process ALL dates")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--no-web-fetch", action="store_true", help="Skip web fetch (faster for old data)")
    args = parser.parse_args()

    dates = get_dates_to_process(
        days_back=args.days_back,
        specific_date=args.date,
        all_dates=args.all,
    )

    if not dates:
        print("All data already in new format!")
        return

    total_todo = 0
    for d in dates:
        path = STRUCTURED / f"{d}.ndjson"
        if path.exists():
            dicts = load_ndjson(path)
            n = sum(1 for item in dicts if not is_new_format(item))
            total_todo += n

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Dates to process: {len(dates)}")
    print(f"Items needing reprocess: {total_todo}")
    print(f"S3 model: {config.S3_MODEL} (concurrency=5)")
    est_minutes = total_todo / 12  # ~12 items/min with concurrency=5
    print(f"Estimated time: ~{est_minutes:.0f} min ({est_minutes/60:.1f} hr)\n")
    print(f"Date range: {dates[0]} → {dates[-1]}\n")

    if args.dry_run:
        for d in dates:
            path = STRUCTURED / f"{d}.ndjson"
            dicts = load_ndjson(path)
            n_todo = sum(1 for i in dicts if not is_new_format(i))
            n_done = sum(1 for i in dicts if is_new_format(i))
            print(f"  {d}: {n_todo} reprocess + {n_done} keep = {len(dicts)} total")
        return

    few_shots = load_few_shots()
    total_reprocessed = 0
    total_skipped = 0
    start_time = time.time()

    for i, date_str in enumerate(dates):
        try:
            reprocessed, skipped = reprocess_date(date_str, few_shots, no_web_fetch=args.no_web_fetch)
            total_reprocessed += reprocessed
            total_skipped += skipped
            elapsed = time.time() - start_time
            rate = total_reprocessed / elapsed * 60 if elapsed > 0 else 0
            remaining = len(dates) - i - 1
            eta_min = (total_todo - total_reprocessed) / (rate / 60) / 60 if rate > 0 else 0
            # Refresh cache periodically
            if (i + 1) % 5 == 0 or i + 1 == len(dates):
                try:
                    build_cache(days=90)
                except Exception:
                    pass
            print(f"  [{i+1}/{len(dates)}] {date_str} done — "
                  f"total reprocessed: {total_reprocessed} | rate: {rate:.1f}/min | ETA: {eta_min:.0f}min")
        except KeyboardInterrupt:
            print("\nInterrupted. Progress saved — safe to resume.")
            break
        except Exception as e:
            log.error("Error on %s: %s", date_str, e)
            continue

    elapsed = time.time() - start_time
    print(f"\n✓ Done. {total_reprocessed} items reprocessed in {elapsed/60:.1f} min.")


if __name__ == "__main__":
    main()
