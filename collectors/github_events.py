"""
GitHub Events collector — detects star spikes for NEW repos.
Uses GitHub API /repos/{owner}/{repo}/stargazers to watch repos that aren't on
trending yet but are gaining stars rapidly (new products going viral).

Strategy:
1. Search GitHub for repos created in last 30 days with AI keywords
2. For each candidate, check current star count vs. age → compute stars/day
3. Flag repos with stars/day > threshold as "new product spike"
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import requests

import config
from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

GH_API = "https://api.github.com"
SEARCH_QUERIES = [
    "agent LLM in:name,description,readme created:>{cutoff} stars:>50",
    "MCP agent in:name,description created:>{cutoff} stars:>30",
    "AI agent tool in:name,description created:>{cutoff} stars:>50",
    "agentic workflow in:name,description created:>{cutoff} stars:>30",
    "personal agent in:name,description created:>{cutoff} stars:>50",
]
STARS_PER_DAY_THRESHOLD = 30   # flag if gaining >30 stars/day on a new repo


class GitHubEventsCollector(BaseCollector):
    source_id = "github_events"

    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "CreekstoneRadar/2.0",
        }
        if config.GITHUB_TOKEN:
            h["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
        return h

    def _collect(self) -> list[SignalItem]:
        now = utcnow()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

        seen_urls: set[str] = set()
        items: list[SignalItem] = []

        for query_tpl in SEARCH_QUERIES:
            query = query_tpl.format(cutoff=cutoff)
            try:
                resp = requests.get(
                    f"{GH_API}/search/repositories",
                    headers=self._headers(),
                    params={
                        "q": query,
                        "sort": "stars",
                        "order": "desc",
                        "per_page": 20,
                    },
                    timeout=20,
                )
                if resp.status_code == 403:
                    log.warning("[github_events] rate limited, sleeping 60s")
                    time.sleep(60)
                    continue
                resp.raise_for_status()
                repos = resp.json().get("items", [])
                time.sleep(1.0)
            except Exception as e:
                log.error("[github_events] search failed: %s", e)
                continue

            for repo in repos:
                url = repo.get("html_url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                created_str = repo.get("created_at", "")
                try:
                    created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    age_days = max(
                        1,
                        (datetime.now(timezone.utc) - created_dt).days
                    )
                except Exception:
                    age_days = 30

                stars = repo.get("stargazers_count", 0)
                stars_per_day = round(stars / age_days, 1)

                if stars_per_day < STARS_PER_DAY_THRESHOLD:
                    continue

                item = SignalItem(
                    id=make_id("github_events", url),
                    source="github_events",
                    collected_at=now,
                    title=repo.get("full_name", ""),
                    url=url,
                    description_en=repo.get("description", "") or "",
                    is_new=age_days <= 30,
                    is_trending=stars_per_day > STARS_PER_DAY_THRESHOLD * 2,
                    metrics={
                        "stars": stars,
                        "stars_per_day": stars_per_day,
                        "age_days": age_days,
                        "forks": repo.get("forks_count", 0),
                        "language": repo.get("language", ""),
                        "created_at": created_str,
                        "topics": repo.get("topics", []),
                        "author": repo.get("owner", {}).get("login", ""),
                    },
                )
                items.append(item)

        items.sort(key=lambda i: i.metrics.get("stars_per_day", 0), reverse=True)
        log.info("[github_events] %d new repos with star spikes", len(items))
        return items
