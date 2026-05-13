"""
arXiv collector — cs.AI / cs.LG / cs.CL papers.
Focuses on Agent frameworks, FDE-related research, A2A protocols.
Filters for papers with code/product references.
"""
from __future__ import annotations
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import requests
from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query"
CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.RO"]
PRODUCT_SIGNALS = {
    "agent", "ai", "model", "framework", "system", "platform",
    "github.com", "open source", "benchmarking",
}
LOOKBACK_DAYS = 30


class ArxivCollector(BaseCollector):
    source_id = "arxiv"

    def _collect(self) -> list[SignalItem]:
        now = utcnow()
        since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
        items: list[SignalItem] = []

        for cat in CATEGORIES:
            try:
                resp = requests.get(
                    ARXIV_API,
                    params={
                        "search_query": f"cat:{cat}+AND+submittedDate:[{since}0000+TO+99991231235959]",
                        "start": 0,
                        "max_results": 30,
                        "sortBy": "submittedDate",
                        "sortOrder": "descending",
                    },
                    timeout=20,
                )
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
                ns = {"atom": "http://www.w3.org/2005/Atom"}

                for entry in root.findall("atom:entry", ns):
                    arxiv_id = entry.findtext("atom:id", namespaces=ns) or ""
                    title = (entry.findtext("atom:title", namespaces=ns) or "").strip().replace("\n", " ")
                    summary = (entry.findtext("atom:summary", namespaces=ns) or "").strip().replace("\n", " ")
                    published = entry.findtext("atom:published", namespaces=ns) or now

                    # Filter: must have product/code signals
                    combined = f"{title} {summary}".lower()
                    if not any(sig in combined for sig in PRODUCT_SIGNALS):
                        continue

                    url = arxiv_id  # e.g. http://arxiv.org/abs/2406.12345v1
                    authors_raw = entry.findall("atom:author/atom:name", ns)
                    authors = [a.text for a in authors_raw if a.text][:5]

                    item = SignalItem(
                        id=make_id("arxiv", url),
                        source="arxiv",
                        collected_at=now,
                        title=title,
                        url=url,
                        description_en=summary[:600],
                        is_new=True,
                        metrics={
                            "arxiv_id": arxiv_id.split("/")[-1],
                            "category": cat,
                            "published": published,
                            "authors": authors,
                            "has_github": "github.com" in combined,
                        },
                    )
                    items.append(item)
                time.sleep(0.5)
            except Exception as e:
                log.error("[arxiv] category %s failed: %s", cat, e)

        # Dedup by arxiv_id
        seen: set[str] = set()
        deduped: list[SignalItem] = []
        for item in items:
            aid = item.metrics.get("arxiv_id", item.url)
            if aid not in seen:
                seen.add(aid)
                deduped.append(item)

        log.info("[arxiv] %d papers collected", len(deduped))
        return deduped
