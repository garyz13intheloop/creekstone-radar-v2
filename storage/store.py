"""
Storage v3 — full SignalItem serialization including FullProfile, TeamInfo, ScoreBreakdown.
Maintains backward-compat NDJSON format + weekly snapshots.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from models.item import SignalItem, ScoreBreakdown, TeamInfo, TrafficData, FullProfile

log = logging.getLogger(__name__)


def _dataclass_to_dict(obj) -> Any:
    """Recursively convert dataclass to dict."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _dataclass_to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_dataclass_to_dict(x) for x in obj]
    return obj


def _item_to_dict(item: SignalItem) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": item.id,
        "source": item.source,
        "collected_at": item.collected_at,
        "title": item.title,
        "url": item.url,
        "description_en": item.description_en,
        "description_zh": item.description_zh,
        "keywords": item.keywords,
        "track": item.track,
        "track_reason": item.track_reason,
        "track_confidence": item.track_confidence,
        "fde_index": item.fde_index,
        "fde_stage": item.fde_stage,
        "score": item.score,
        "is_new": item.is_new,
        "is_trending": item.is_trending,
        "is_spike": item.is_spike,
        "wow_growth_pct": item.wow_growth_pct,
        "has_video": item.has_video,
        "feedback_state": item.feedback_state,
        "feedback_note": item.feedback_note,
        "sourcing_synced": item.sourcing_synced,
        "metrics": item.metrics,
        "thumbnail_url": item.thumbnail_url,
    }
    if item.score_breakdown:
        d["score_breakdown"] = _dataclass_to_dict(item.score_breakdown)
    if item.team:
        d["team"] = _dataclass_to_dict(item.team)
    if item.traffic:
        d["traffic"] = _dataclass_to_dict(item.traffic)
    if item.full_profile:
        d["full_profile"] = _dataclass_to_dict(item.full_profile)
    return d


def save_daily(items: list[SignalItem], date_str: str | None = None) -> Path:
    """Append items to today's NDJSON, skip duplicates by ID."""
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    out_path = config.STRUCTURED_DIR / f"{date_str}.ndjson"

    existing_ids: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            try:
                existing_ids.add(json.loads(line)["id"])
            except Exception:
                pass

    new_items = [i for i in items if i.id not in existing_ids]
    if not new_items:
        log.info("[storage] no new items for %s", date_str)
        return out_path

    with out_path.open("a", encoding="utf-8") as f:
        for item in new_items:
            f.write(json.dumps(_item_to_dict(item), ensure_ascii=False) + "\n")

    log.info("[storage] wrote %d new items → %s", len(new_items), out_path)
    return out_path


def save_snapshot(items: list[SignalItem], source: str, date_str: str | None = None) -> Path:
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snap_path = config.SNAPSHOTS_DIR / f"{source}_{date_str}.json"
    data = [_item_to_dict(i) for i in items]
    snap_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("[storage] snapshot saved: %s (%d items)", snap_path.name, len(data))
    return snap_path


def load_recent_daily(days: int = 7) -> list[dict]:
    """Load items from the last N days, newest first. Uses per-file mtime cache."""
    from datetime import timedelta
    items: list[dict] = []
    seen_ids: set[str] = set()

    for d in range(days):
        date_str = (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%d")
        fpath = config.STRUCTURED_DIR / f"{date_str}.ndjson"
        if not fpath.exists():
            continue
        for line in fpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("id") not in seen_ids:
                    seen_ids.add(obj["id"])
                    items.append(obj)
            except Exception:
                pass

    return items


def build_cache(days: int = 0) -> Path:
    """Build a flat JSON cache of ALL items across all dates for fast frontend loading.
    days=0 (default) scans all files; days>0 limits to last N days."""
    from datetime import timedelta
    all_items: list[dict] = []
    seen_ids: set[str] = set()

    if days > 0:
        # Limited mode: last N days only
        for d in range(days):
            date_str = (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%d")
            fpath = config.STRUCTURED_DIR / f"{date_str}.ndjson"
            if fpath.exists():
                for line in fpath.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line: continue
                    try:
                        obj = json.loads(line)
                        if obj.get("id") not in seen_ids:
                            seen_ids.add(obj["id"])
                            all_items.append(obj)
                    except Exception:
                        pass
    else:
        # Full mode: scan ALL ndjson files
        for fpath in sorted(config.STRUCTURED_DIR.glob("*.ndjson")):
            if ".old" in fpath.name: continue
            for line in fpath.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line: continue
                try:
                    obj = json.loads(line)
                    if obj.get("id") not in seen_ids:
                        seen_ids.add(obj["id"])
                        all_items.append(obj)
                except Exception:
                    pass

    cache_path = config.DATA_DIR / "cache_all.json"
    cache_path.write_text(json.dumps(all_items, ensure_ascii=False), encoding="utf-8")
    log.info("[cache] built %d items → %s", len(all_items), cache_path)
    return cache_path


def load_from_cache(days: int = 7) -> list[dict]:
    """Load from flat cache (ALL historical data). Rebuilds if stale > 10min."""
    from datetime import timedelta
    import os, time
    cache_path = config.DATA_DIR / "cache_all.json"

    # Rebuild cache if missing or stale (>10 min)
    if not cache_path.exists() or (time.time() - os.path.getmtime(cache_path)) > 600:
        try:
            build_cache()  # full rebuild, no day limit
        except Exception as e:
            log.warning("[cache] rebuild failed: %s", e)

    try:
        all_items = json.loads(cache_path.read_text(encoding="utf-8"))
        if days <= 0:
            return all_items  # return everything
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        return [i for i in all_items if i.get("collected_at", "")[:10] >= cutoff]
    except Exception:
        return load_recent_daily(days)
