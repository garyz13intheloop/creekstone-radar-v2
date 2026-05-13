"""
Product Hunt collector — GraphQL API.
Refactored from v1 for cleaner output and unified SignalItem model.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests

import config
from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

PH_GQL_URL = "https://api.producthunt.com/v2/api/graphql"

GQL_QUERY = """
query GetPosts($after: String) {
  posts(order: VOTES, postedAfter: $postedAfter, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id name tagline description votesCount
        reviewsRating reviewsCount
        createdAt website
        thumbnail { url }
        topics { edges { node { name } } }
        makers { id name username }
      }
    }
  }
}
"""

AI_TOPICS = {
    "artificial intelligence", "developer tools", "bots", "github",
    "machine learning", "productivity", "open source", "saas",
    "developer api", "automation", "no-code", "browser extensions",
}
AI_KEYWORDS = {
    "ai", "agent", "llm", "gpt", "claude", "mcp", "rag", "copilot",
    "automation", "chatbot", "workflow", "embedding", "multimodal",
}


class ProductHuntCollector(BaseCollector):
    source_id = "producthunt"

    def _collect(self) -> list[SignalItem]:
        if not config.PH_TOKEN:
            log.warning("[producthunt] no token, skipping")
            return []

        now = utcnow()
        # 强制拉取过去 30 天数据
        posted_after = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        headers = {
            "Authorization": f"Bearer {config.PH_TOKEN}",
            "Content-Type": "application/json",
        }
        cursor = None
        items: list[SignalItem] = []

        for _ in range(3):  # max 3 pages
            try:
                variables: dict = {"postedAfter": posted_after}
                if cursor:
                    variables["after"] = cursor

                resp = requests.post(
                    PH_GQL_URL,
                    json={"query": GQL_QUERY, "variables": variables},
                    headers=headers,
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()
                posts_data = data.get("data", {}).get("posts", {})
            except Exception as e:
                log.error("[producthunt] API call failed: %s", e)
                break

            edges = posts_data.get("edges", [])
            for edge in edges:
                node = edge.get("node", {})
                topics = [
                    e["node"]["name"].lower()
                    for e in node.get("topics", {}).get("edges", [])
                ]
                name = node.get("name", "")
                tagline = node.get("tagline", "")
                description = node.get("description", "")
                merged = f"{name} {tagline} {description}".lower()

                is_ai = (
                    any(t in AI_TOPICS for t in topics)
                    or any(k in merged for k in AI_KEYWORDS)
                )
                if not is_ai:
                    continue

                votes = node.get("votesCount", 0)
                website = node.get("website", "") or ""
                url = website or f"https://www.producthunt.com/posts/{name.lower().replace(' ', '-')}"
                makers = [
                    m.get("username", "") for m in node.get("makers", [])
                ]

                item = SignalItem(
                    id=make_id("producthunt", url),
                    source="producthunt",
                    collected_at=now,
                    title=name,
                    url=url,
                    description_en=f"{tagline}. {description}"[:600],
                    is_trending=votes > 200,
                    thumbnail_url=(node.get("thumbnail") or {}).get("url"),
                    metrics={
                        "votes": votes,
                        "reviews_rating": node.get("reviewsRating", 0),
                        "reviews_count": node.get("reviewsCount", 0),
                        "topics": topics,
                        "makers": makers,
                        "ph_created_at": node.get("createdAt", ""),
                        "ph_url": f"https://www.producthunt.com/posts/{name.lower().replace(' ', '-')}",
                    },
                )
                items.append(item)

            page_info = posts_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        items.sort(key=lambda i: i.metrics.get("votes", 0), reverse=True)
        log.info("[producthunt] %d AI products collected", len(items))
        return items
