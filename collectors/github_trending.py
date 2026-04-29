"""
GitHub Trending collector — scrapes github.com/trending.
Improved over v1: single LLM call downstream, simpler parsing, dedup by URL.
"""
from __future__ import annotations

import logging
import re
import time

import requests
from bs4 import BeautifulSoup

import config
from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

AI_KEYWORDS = {
    "ai", "agent", "llm", "gpt", "claude", "gemini", "mcp", "rag",
    "embedding", "inference", "transformer", "diffusion", "multimodal",
    "autonomous", "copilot", "chatbot", "assistant", "langchain", "openai",
    "anthropic", "agentic", "workflow", "vector", "semantic", "generative",
}
EXCLUDE_KEYWORDS = {"crypto", "nft", "blockchain", "casino", "porn", "betting"}

TRENDING_URL = "https://github.com/trending"
GH_HEADERS = {
    "User-Agent": "CreekstoneRadar/2.0",
    "Accept": "text/html",
}


class GitHubTrendingCollector(BaseCollector):
    source_id = "github_trending"

    def _collect(self) -> list[SignalItem]:
        now = utcnow()
        items: list[SignalItem] = []

        for since in ("daily", "weekly"):
            try:
                resp = requests.get(
                    TRENDING_URL,
                    params={"since": since},
                    headers=GH_HEADERS,
                    timeout=20,
                )
                resp.raise_for_status()
                repos = _parse_trending(resp.text, since, now)
                items.extend(repos)
                time.sleep(0.8)
            except Exception as e:
                log.error("[github_trending] failed for since=%s: %s", since, e)

        # Dedup (daily+weekly may overlap)
        seen: set[str] = set()
        deduped: list[SignalItem] = []
        for item in items:
            if item.url not in seen:
                seen.add(item.url)
                deduped.append(item)

        log.info("[github_trending] %d repos after dedup", len(deduped))
        return deduped


def _parse_trending(html: str, since: str, now: str) -> list[SignalItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[SignalItem] = []

    for article in soup.find_all("article", class_="Box-row"):
        try:
            h2 = article.find("h2", class_="h3")
            if not h2:
                continue
            a_tag = h2.find("a")
            if not a_tag:
                continue

            full_name = a_tag.get("href", "").strip("/")
            if "/" not in full_name:
                continue
            author, name = full_name.split("/", 1)
            url = f"https://github.com/{full_name}"

            desc_tag = article.find("p", class_="col-9")
            desc = desc_tag.get_text(strip=True) if desc_tag else ""

            lang_tag = article.find("span", attrs={"itemprop": "programmingLanguage"})
            language = lang_tag.get_text(strip=True) if lang_tag else ""

            stars = _parse_num(article.find("svg", class_="octicon-star"))
            forks = _parse_num(article.find("svg", class_="octicon-repo-forked"))

            today_tag = article.find("span", class_="d-inline-block float-sm-right")
            stars_today = _parse_num_text(today_tag.get_text() if today_tag else "0")

            # AI filter
            merged_text = f"{name} {desc}".lower()
            if not any(k in merged_text for k in AI_KEYWORDS):
                continue
            if any(k in merged_text for k in EXCLUDE_KEYWORDS):
                continue

            item = SignalItem(
                id=make_id("github_trending", url),
                source="github_trending",
                collected_at=now,
                title=f"{author}/{name}",
                url=url,
                description_en=desc,
                is_trending=(since == "daily" and stars_today > config.GITHUB_STARS_SPIKE_THRESHOLD),
                metrics={
                    "stars": stars,
                    "forks": forks,
                    "stars_today": stars_today,
                    "language": language,
                    "since": since,
                    "author": author,
                    "repo_name": name,
                },
            )
            items.append(item)

        except Exception as e:
            log.debug("parse error for article: %s", e)
            continue

    return items


def _parse_num(svg_tag) -> int:
    if not svg_tag:
        return 0
    parent = svg_tag.find_parent("a")
    if not parent:
        return 0
    return _parse_num_text(parent.get_text(strip=True))


def _parse_num_text(text: str) -> int:
    text = text.strip().replace(",", "").lower()
    m = re.search(r"([\d.]+)k?", text)
    if not m:
        return 0
    val = float(m.group(1))
    return int(val * 1000 if "k" in text else val)
