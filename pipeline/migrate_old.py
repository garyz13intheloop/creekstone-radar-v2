"""
Migration script: Old pipeline NJSON → New pipeline SignalItem (JSONL format).
"""
import json
from pathlib import Path
from datetime import datetime, timezone

OLD_JSON = Path("/Users/garyzhang/CreekStone-SearchBot/data/structured/items.ndjson")
NEW_DIR = Path("/Users/garyzhang/creekstone-radar-v2/data/structured")

def migrate():
    if not OLD_JSON.exists():
        print("Old data not found.")
        return

    # Group items by date
    by_date = {}
    
    with OLD_JSON.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                old = json.loads(line)
                # Map fields
                date_str = old.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                
                # Create item dict
                new = {
                    "id": old.get("id", ""),
                    "source": old.get("source", "unknown"),
                    "collected_at": old.get("date", datetime.now(timezone.utc).isoformat()),
                    "title": old.get("title", ""),
                    "url": old.get("url", ""),
                    "description_en": old.get("description_en", ""),
                    "description_zh": old.get("description_zh", ""),
                    "keywords": old.get("keywords", []),
                    "score": 0.0,
                    "metrics": old.get("metrics", {}),
                    "is_new": False,
                    "is_trending": False,
                    "wow_growth_pct": None,
                    "has_video": False,
                    "feedback_state": "pending",
                    "track": "unknown",
                }
                
                if date_str not in by_date:
                    by_date[date_str] = []
                by_date[date_str].append(new)
            except:
                continue

    # Write files
    for d, items in by_date.items():
        out = NEW_DIR / f"{d}.ndjson"
        with out.open("a", encoding="utf-8") as f:
            for i in items:
                f.write(json.dumps(i, ensure_ascii=False) + "\n")
        print(f"Migrated {len(items)} items to {out.name}")

if __name__ == "__main__":
    migrate()
