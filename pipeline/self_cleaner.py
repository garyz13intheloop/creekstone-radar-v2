"""
Self-cleaner — runs weekly to remove dead URLs, archive stale items,
and detect cross-source duplicates.
"""
from __future__ import annotations
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
import config

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEAD_TIMEOUT = 8
STALE_DAYS = 30


def check_url(url: str) -> bool:
    """Return True if URL is alive."""
    if not url or url.startswith("http://arxiv.org/abs"):
        return True  # arXiv stable
    try:
        r = requests.head(url, timeout=DEAD_TIMEOUT, allow_redirects=True,
                         headers={"User-Agent": "CreekstoneRadar/2.0"})
        return r.status_code < 400
    except Exception:
        return False


def run_cleanup() -> dict:
    now = datetime.now(timezone.utc)
    stale_cutoff = (now - timedelta(days=STALE_DAYS)).isoformat()
    stats = {"checked": 0, "dead": 0, "archived": 0}

    # Process all NDJSON files
    for ndjson_path in sorted(config.STRUCTURED_DIR.glob("*.ndjson")):
        lines_in = ndjson_path.read_text(encoding="utf-8").splitlines()
        lines_out = []
        modified = False

        for line in lines_in:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                lines_out.append(line)
                continue

            url = item.get("url", "")
            collected = item.get("collected_at", "")
            feedback_state = item.get("feedback_state", "pending")

            # Archive stale non-watchlist items
            if collected < stale_cutoff and feedback_state not in ("watchlist", "interested"):
                item["archived"] = True
                stats["archived"] += 1
                modified = True

            # Dead URL check (only for non-archived, non-watchlist)
            if not item.get("archived") and feedback_state != "watchlist":
                stats["checked"] += 1
                if not check_url(url):
                    item["inactive"] = True
                    stats["dead"] += 1
                    modified = True
                    log.info("Dead URL: %s", url[:60])
                time.sleep(0.2)

            lines_out.append(json.dumps(item, ensure_ascii=False))

        if modified:
            ndjson_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")

    log.info("Cleanup complete: checked=%d dead=%d archived=%d",
             stats["checked"], stats["dead"], stats["archived"])
    return stats


if __name__ == "__main__":
    run_cleanup()
