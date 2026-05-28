"""
Web content enricher — fetches real page content before S3 scoring.
Uses Jina Reader (r.jina.ai) to get clean markdown from any URL.
Called between S2 and S3 to fill in thin description_en fields.
"""
from __future__ import annotations
import logging
import time
import requests
from models.item import SignalItem

log = logging.getLogger(__name__)

JINA_TIMEOUT = 12
MIN_DESC_LEN = 200   # fetch if description_en is shorter than this
MAX_FETCH_PER_RUN = 60  # cap to avoid slowdowns


def _fetch_jina(url: str) -> str:
    """Fetch clean markdown via Jina Reader."""
    try:
        r = requests.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/plain", "X-Return-Format": "markdown"},
            timeout=JINA_TIMEOUT,
        )
        if r.status_code == 200 and len(r.text) > 100:
            # Trim to first 1200 chars — enough context, not too expensive for LLM
            return r.text[:1200].strip()
    except Exception:
        pass
    return ""


def _should_fetch(item: SignalItem) -> bool:
    """Decide whether this item needs web fetch."""
    desc_len = len(item.description_en or "")
    if desc_len >= MIN_DESC_LEN:
        return False
    # Don't fetch arXiv (description is already the abstract)
    if item.source == "arxiv":
        return False
    # Don't fetch X/Twitter (text is the tweet)
    if item.source == "x_twitter":
        return False
    return True


def enrich_descriptions(items: list[SignalItem]) -> list[SignalItem]:
    """
    For items with thin description_en, fetch real content via Jina.
    Appends fetched content to description_en so S3 has more signal.
    """
    needs_fetch = [i for i in items if _should_fetch(i)]
    log.info("[web_enrich] %d/%d items need web fetch", len(needs_fetch), len(items))

    fetched = 0
    for item in needs_fetch[:MAX_FETCH_PER_RUN]:
        content = _fetch_jina(item.url)
        if content:
            # Append to existing description
            existing = item.description_en or ""
            item.description_en = (existing + "\n\n" + content)[:1800]
            fetched += 1
            log.debug("[web_enrich] fetched %d chars for '%s'", len(content), item.title[:40])
        time.sleep(0.3)  # gentle rate limit

    log.info("[web_enrich] successfully fetched %d/%d", fetched, len(needs_fetch))
    return items
