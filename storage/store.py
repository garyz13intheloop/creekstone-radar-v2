"""
Storage — NDJSON-based, same format as v1 for backward compatibility.
Adds weekly snapshot support for WoW growth tracking.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from models.item import SignalItem

log = logging.getLogger(__name__)


def _item_to_dict(item: SignalItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "source": item.source,
        "collected_at": item.collected_at,
        "title": item.title,
        "url": item.url,
        "description_en": item.description_en,
        "description_zh": item.description_zh,
        "keywords": item.keywords,
        "score": item.score,
        "metrics": item.metrics,
        "is_new": item.is_new,
        "is_trending": item.is_trending,
        "wow_growth_pct": item.wow_growth_pct,
        "thumbnail_url": item.thumbnail_url,
        "has_video": item.has_video,
    }


def save_daily(items: list[SignalItem], date_str: str | None = None) -> Path:
    """Append items to today's NDJSON file."""
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    out_path = config.STRUCTURED_DIR / f"{date_str}.ndjson"

    # Load existing IDs to avoid duplicates
    existing_ids: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            try:
                existing_ids.add(json.loads(line)["id"])
            except Exception:
                pass

    new_items = [i for i in items if i.id not in existing_ids]
    if not new_items:
        log.info("[storage] no new items to write for %s", date_str)
        return out_path

    with out_path.open("a", encoding="utf-8") as f:
        for item in new_items:
            f.write(json.dumps(_item_to_dict(item), ensure_ascii=False) + "\n")

    log.info("[storage] wrote %d new items → %s", len(new_items), out_path)
    return out_path


def save_snapshot(items: list[SignalItem], source: str, date_str: str | None = None) -> Path:
    """
    Save a weekly snapshot for WoW comparison.
    Used by OpenRouter and HuggingFace to track growth over time.
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    snap_path = config.SNAPSHOTS_DIR / f"{source}_{date_str}.json"
    data = [_item_to_dict(i) for i in items]
    snap_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("[storage] snapshot saved: %s (%d items)", snap_path.name, len(data))
    return snap_path


def load_recent_daily(days: int = 7) -> list[dict]:
    """Load all items from last N days of NDJSON files."""
    items: list[dict] = []
    for f in sorted(config.STRUCTURED_DIR.glob("*.ndjson"), reverse=True)[:days]:
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                items.append(json.loads(line))
            except Exception:
                pass
    return items
