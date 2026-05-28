"""
arXiv collector v3 — RSS-based, no rate limit.
每天从 cs.AI / cs.LG / cs.CL / cs.RO 的 RSS 抓当日新论文。
RSS 每天更新一次，稳定可靠，不触发 API 限速。
"""
from __future__ import annotations
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

RSS_FEEDS = [
    "https://arxiv.org/rss/cs.AI",
    "https://arxiv.org/rss/cs.LG",
    "https://arxiv.org/rss/cs.CL",
    "https://arxiv.org/rss/cs.RO",
]

AGENT_KEYWORDS = {
    "agent", "agentic", "autonomous", "multi-agent",
    "mcp", "tool use", "tool-use", "llm", "language model",
    "rag", "retrieval", "embedding", "reasoning",
    "copilot", "code generation", "robot", "embodied",
    "transformer", "diffusion", "multimodal", "vision",
    "benchmark", "fine-tun", "instruction", "alignment",
    "chain-of-thought", "prompt", "in-context",
}

HEADERS = {"User-Agent": "CreekstoneRadar/3.0 (research; https://creekstone.vc)"}
MAX_PER_FEED = 80   # RSS 每个 feed 最多取前80条（今日新增）


class ArxivCollector(BaseCollector):
    source_id = "arxiv"

    def _collect(self) -> list[SignalItem]:
        now = utcnow()
        seen_ids: set[str] = set()
        items: list[SignalItem] = []

        for feed_url in RSS_FEEDS:
            cat = feed_url.split("/")[-1]  # cs.AI, cs.LG, etc.
            try:
                resp = requests.get(feed_url, headers=HEADERS, timeout=20)
                resp.raise_for_status()
                feed_items = self._parse_rss(resp.text, cat, now, seen_ids)
                items.extend(feed_items)
                log.info("[arxiv] RSS %s: %d papers", cat, len(feed_items))
                time.sleep(1)
            except Exception as e:
                log.warning("[arxiv] RSS %s failed: %s", cat, e)

        log.info("[arxiv] total %d papers", len(items))
        return items

    def _parse_rss(
        self, xml_text: str, category: str, now: str, seen_ids: set[str]
    ) -> list[SignalItem]:
        items: list[SignalItem] = []

        ITEM_RE  = re.compile(r'<item>(.*?)</item>', re.DOTALL)
        TITLE_RE = re.compile(r'<title>(.*?)</title>', re.DOTALL)
        LINK_RE  = re.compile(r'<link>(https://arxiv\.org/abs/[^<]+)</link>')
        DESC_RE  = re.compile(r'<description>(.*?)</description>', re.DOTALL)

        count = 0
        for m in ITEM_RE.finditer(xml_text):
            if count >= MAX_PER_FEED:
                break
            block = m.group(1)

            t_m = TITLE_RE.search(block)
            l_m = LINK_RE.search(block)
            if not t_m or not l_m:
                continue

            title = t_m.group(1).strip()
            link  = l_m.group(1).strip()
            d_m   = DESC_RE.search(block)
            desc_raw = d_m.group(1) if d_m else ""
            desc_clean = re.sub(r"<[^>]+>", " ", desc_raw).strip()
            desc_clean = re.sub(r"\s+", " ", desc_clean)

            arxiv_id = link.split("/abs/")[-1].split("v")[0].strip()
            if arxiv_id in seen_ids:
                continue

            combined = f"{title} {desc_clean}".lower()
            if not any(kw in combined for kw in AGENT_KEYWORDS):
                continue

            authors = []
            a_m = re.search(r"Authors?:\s*([^\n<]+)", desc_raw, re.IGNORECASE)
            if a_m:
                authors = [a.strip() for a in a_m.group(1).split(",")][:5]

            seen_ids.add(arxiv_id)
            item = SignalItem(
                id=make_id("arxiv", link),
                source="arxiv",
                collected_at=now,
                title=title,
                url=link,
                description_en=desc_clean[:800],
                is_new=True,
                track="Tech",
                track_reason="arXiv论文，自动归入Tech Track",
                track_confidence="high",
                metrics={
                    "arxiv_id": arxiv_id,
                    "category": category,
                    "authors": authors,
                    "has_github": "github.com" in combined,
                },
            )
            items.append(item)
            count += 1

        return items
