"""
X / Twitter collector — OAuth 1.0a search.
Monitors product launch signals: demo videos, launch keywords, AI/Agent mentions.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from requests_oauthlib import OAuth1

import config
from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

# Queries targeting different launch signal types
SEARCH_QUERIES = [
    # Direct launch signals — must mention tech-specific terms
    '("just launched" OR "we launched" OR "launching today") ("AI agent" OR "MCP" OR "agentic" OR "LLM tool") -is:retweet lang:en -politics -election',
    # Build in public + product links
    '("#buildinpublic" OR "#shipitsaturday" OR "Product Hunt") (agent OR MCP OR agentic OR "vibe coding") -is:retweet lang:en has:links',
    # Demo video with tech content — strongest launch signal
    '("AI agent" OR "MCP server" OR "agentic" OR "Claude" OR "Cursor") -is:retweet lang:en has:videos has:links',
    # GitHub + AI launches
    '("github.com" OR "open source") ("AI agent" OR "MCP" OR "LLM" OR "agentic workflow") -is:retweet lang:en has:links',
]

MAX_RESULTS_PER_QUERY = 50  # max per search call on Basic tier
LOOKBACK_HOURS = 26          # slightly >24h to avoid gaps


class XTwitterCollector(BaseCollector):
    source_id = "x_twitter"

    def __init__(self):
        self._auth = OAuth1(
            config.X_API_KEY,
            config.X_API_SECRET,
            config.X_ACCESS_TOKEN,
            config.X_ACCESS_TOKEN_SECRET,
        )

    def _search(self, query: str, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
        """Call Twitter v2 recent search, returns raw tweet dicts."""
        start_time = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        params: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "start_time": start_time,
            "tweet.fields": "created_at,public_metrics,author_id,attachments,entities",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "username,name,public_metrics,verified",
            "media.fields": "type,duration_ms",
        }
        try:
            r = requests.get(
                "https://api.twitter.com/2/tweets/search/recent",
                auth=self._auth,
                params=params,
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            return data.get("data", []), data.get("includes", {})
        except Exception as e:
            log.warning("[x_twitter] search failed for query '%s': %s", query[:60], e)
            return [], {}

    def _collect(self) -> list[SignalItem]:
        if not config.X_API_KEY:
            log.warning("[x_twitter] no credentials, skipping")
            return []

        now = utcnow()
        seen_ids: set[str] = set()
        items: list[SignalItem] = []

        for query in SEARCH_QUERIES:
            tweets, includes = self._search(query)
            time.sleep(1.5)  # rate-limit courtesy

            # Build user map
            users = {u["id"]: u for u in includes.get("users", [])}
            # Build media map
            media_map: dict[str, str] = {}
            for m in includes.get("media", []):
                media_map[m.get("media_key", "")] = m.get("type", "")

            for tweet in tweets:
                tweet_id = tweet["id"]
                if tweet_id in seen_ids:
                    continue
                seen_ids.add(tweet_id)

                metrics = tweet.get("public_metrics", {})
                likes = metrics.get("like_count", 0)
                bookmarks = metrics.get("bookmark_count", 0)
                retweets = metrics.get("retweet_count", 0)
                impressions = metrics.get("impression_count", 0)

                # Filter: minimum engagement
                if likes < config.X_MIN_LIKES and bookmarks < 5:
                    continue

                author_id = tweet.get("author_id", "")
                author = users.get(author_id, {})
                username = author.get("username", "unknown")
                author_metrics = author.get("public_metrics", {})

                text = tweet.get("text", "")
                created_at = tweet.get("created_at", now)

                # Detect URLs in tweet
                tweet_url = f"https://x.com/{username}/status/{tweet_id}"
                urls = [
                    u.get("expanded_url", "")
                    for u in tweet.get("entities", {}).get("urls", [])
                    if u.get("expanded_url", "") and "twitter.com" not in u.get("expanded_url", "")
                    and "t.co" not in u.get("expanded_url", "")
                ]
                product_url = urls[0] if urls else tweet_url

                # Detect video
                media_keys = tweet.get("attachments", {}).get("media_keys", [])
                has_video = any(media_map.get(k, "") == "video" for k in media_keys)

                # Compute virality score (weighted signal)
                virality = likes * 1 + bookmarks * 3 + retweets * 2 + (impressions / 1000)
                is_trending = virality > 200 or impressions > 50000

                item = SignalItem(
                    id=make_id("x_twitter", tweet_url),
                    source="x_twitter",
                    collected_at=now,
                    title=_extract_title(text, username),
                    url=tweet_url,
                    description_en=text[:500],
                    is_trending=is_trending,
                    has_video=has_video,
                    metrics={
                        "likes": likes,
                        "retweets": retweets,
                        "bookmarks": bookmarks,
                        "impressions": impressions,
                        "replies": metrics.get("reply_count", 0),
                        "virality_score": round(virality, 1),
                        "username": username,
                        "author_followers": author_metrics.get("followers_count", 0),
                        "created_at": created_at,
                        "has_video": has_video,
                        "product_url": product_url,
                        "query_matched": query[:80],
                    },
                    raw={"full_text": text, "tweet_id": tweet_id},
                )
                items.append(item)

        # Sort by virality
        items.sort(key=lambda i: i.metrics.get("virality_score", 0), reverse=True)
        log.info("[x_twitter] %d qualifying tweets from %d queries", len(items), len(SEARCH_QUERIES))
        return items


def _extract_title(text: str, username: str) -> str:
    """Extract a short title from tweet text."""
    # Remove URLs and @mentions from first line
    first_line = text.split("\n")[0]
    first_line = re.sub(r"https?://\S+", "", first_line).strip()
    first_line = re.sub(r"@\w+", "", first_line).strip()
    if len(first_line) > 80:
        first_line = first_line[:77] + "..."
    return first_line or f"Tweet by @{username}"
