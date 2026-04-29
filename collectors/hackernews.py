"""
Hacker News collector — monitors Show HN and recent AI/Agent posts.
Uses Algolia HN Search API (free, no key needed, ~5min delay).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"

HN_QUERIES = [
    "Show HN: agent",
    "Show HN: MCP",
    "Show HN: AI tool",
    "Show HN: LLM",
    "Show HN: agentic",
    "Ask HN: agent",
]

MIN_POINTS = 5      # ignore low-signal posts
LOOKBACK_HOURS = 48


class HackerNewsCollector(BaseCollector):
    source_id = "hackernews"

    def _collect(self) -> list[SignalItem]:
        now = utcnow()
        cutoff = int(
            (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp()
        )
        seen: set[str] = set()
        items: list[SignalItem] = []

        for query in HN_QUERIES:
            try:
                resp = requests.get(
                    ALGOLIA_SEARCH,
                    params={
                        "query": query,
                        "tags": "story",
                        "numericFilters": f"created_at_i>{cutoff},points>{MIN_POINTS}",
                        "hitsPerPage": 30,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                hits = resp.json().get("hits", [])
                time.sleep(0.3)
            except Exception as e:
                log.error("[hackernews] query '%s' failed: %s", query, e)
                continue

            for hit in hits:
                hn_id = str(hit.get("objectID", ""))
                if hn_id in seen:
                    continue
                seen.add(hn_id)

                title = hit.get("title", "")
                url = hit.get("url") or f"https://news.ycombinator.com/item?id={hn_id}"
                points = hit.get("points", 0)
                num_comments = hit.get("num_comments", 0)
                created_iso = hit.get("created_at", now)

                item = SignalItem(
                    id=make_id("hackernews", url),
                    source="hackernews",
                    collected_at=now,
                    title=title,
                    url=url,
                    description_en=f"HN: {title}. Points: {points}, comments: {num_comments}.",
                    is_trending=points > 100,
                    metrics={
                        "points": points,
                        "comments": num_comments,
                        "hn_id": hn_id,
                        "hn_url": f"https://news.ycombinator.com/item?id={hn_id}",
                        "created_at": created_iso,
                        "author": hit.get("author", ""),
                        "query_matched": query,
                    },
                )
                items.append(item)

        items.sort(key=lambda i: i.metrics.get("points", 0), reverse=True)
        log.info("[hackernews] %d posts collected", len(items))
        return items
