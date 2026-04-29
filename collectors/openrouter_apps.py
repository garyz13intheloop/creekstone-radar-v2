"""
OpenRouter App & Agent Rankings collector.
Scrapes openrouter.ai/apps via Jina Reader (free, no API key needed).
Captures: Most Popular, Trending (WoW growth), Global Ranking, category tops.
"""
from __future__ import annotations

import re
import time
import logging
import requests

from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

JINA_BASE = "https://r.jina.ai/https://openrouter.ai/apps"
CATEGORY_PAGES = {
    "coding": "https://r.jina.ai/https://openrouter.ai/apps/category/coding",
    "personal_agent": "https://r.jina.ai/https://openrouter.ai/apps/category/productivity/personal-agent",
    "productivity": "https://r.jina.ai/https://openrouter.ai/apps/category/productivity",
}
JINA_HEADERS = {"Accept": "text/markdown", "User-Agent": "CreekstoneRadar/2.0"}

# Jina renders Markdown like:
#   Trending entry: [![Image N: Favicon...](img_url) AppName 98.6B+4313%](app_url)
#   Global entry:   [N. [![Image N: ...](img_url) AppName Desc Cats 287B tokens](app_url)
TRENDING_RE = re.compile(
    r"\[!\[[^\]]*\]\([^)]+\)\s*([^0-9\]]+?)\s*([\d.]+[TBMK])\+(\d[\d,]+%)"
    r"\]\(https://openrouter\.ai/apps/([^)]+)\)"
)
GLOBAL_RE = re.compile(
    r"\[(\d+)\.\s*!\[[^\]]*\]\([^)]+\)\s*([^\[]+?)\s*([\d.]+[TBMK])\s*tokens\]"
    r"\(https://openrouter\.ai/apps/([^)]+)\)"
)
CATEGORY_RE = re.compile(
    r"\[!\[[^\]]*\]\([^)]+\)\s*([^\[\]]+?)\s*([\d.]+[TBMK])\s*tokens\]"
    r"\(https://openrouter\.ai/apps/([^)]+)\)"
)


def _fetch(url: str) -> str:
    resp = requests.get(url, headers=JINA_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def _parse_tokens(raw: str) -> int:
    raw = raw.strip().upper()
    m = re.match(r"([\d.]+)([TBMK]?)", raw)
    if not m:
        return 0
    v = float(m.group(1))
    mult = {"T": 1_000_000_000_000, "B": 1_000_000_000, "M": 1_000_000, "K": 1_000}.get(m.group(2), 1)
    return int(v * mult)


def _parse_wow(raw: str) -> float:
    m = re.search(r"([\d,]+)%", raw)
    return float(m.group(1).replace(",", "")) if m else 0.0


class OpenRouterAppsCollector(BaseCollector):
    source_id = "openrouter"

    def _collect(self) -> list[SignalItem]:
        items: dict[str, SignalItem] = {}
        now = utcnow()

        try:
            md = _fetch(JINA_BASE)
            time.sleep(0.5)
        except Exception as e:
            log.error("[openrouter] failed to fetch main page: %s", e)
            return []

        # ── Trending (WoW growth) ──────────────────────────────────────────────
        trending_idx = md.find("## Trending")
        global_idx = md.find("## Global Ranking")
        trending_block = md[trending_idx:global_idx] if trending_idx >= 0 and global_idx > trending_idx else ""

        for m in TRENDING_RE.finditer(trending_block):
            name, tokens_raw, wow_raw, slug = m.group(1).strip(), m.group(2), m.group(3), m.group(4)
            app_url = f"https://openrouter.ai/apps/{slug}"
            wow = _parse_wow(wow_raw)
            item = SignalItem(
                id=make_id("openrouter", app_url),
                source="openrouter",
                collected_at=now,
                title=name,
                url=app_url,
                description_en=f"Trending on OpenRouter App Rankings. WoW growth: +{wow:.0f}%.",
                is_trending=True,
                wow_growth_pct=wow,
                metrics={
                    "tokens_week": tokens_raw,
                    "tokens_int": _parse_tokens(tokens_raw),
                    "wow_pct": wow,
                    "section": "trending",
                    "categories": [],
                    "rank_global": None,
                },
            )
            items[app_url] = item

        # ── Global Ranking (weekly token volume, ranked) ───────────────────────
        global_block = md[global_idx:] if global_idx >= 0 else ""

        for m in GLOBAL_RE.finditer(global_block):
            rank_str, middle, tokens_raw, slug = m.groups()
            rank = int(rank_str)
            app_url = f"https://openrouter.ai/apps/{slug}"

            # Extract categories from middle text
            cats = re.findall(
                r"(Personal Agents?|CLI Agents?|IDE Extensions?|Cloud Agents?|Coding|"
                r"Productivity|Roleplay|Creative|Game|Video Generation|Programming App)",
                middle, re.I
            )
            # Clean name (first segment before repeated description)
            name_raw = middle.strip()
            name = name_raw.split(" ")[0] if name_raw else slug

            tokens_int = _parse_tokens(tokens_raw)

            if app_url in items:
                items[app_url].metrics["rank_global"] = rank
                items[app_url].metrics["categories"] = cats or items[app_url].metrics.get("categories", [])
                items[app_url].metrics["tokens_week"] = tokens_raw
                items[app_url].metrics["tokens_int"] = tokens_int
            else:
                item = SignalItem(
                    id=make_id("openrouter", app_url),
                    source="openrouter",
                    collected_at=now,
                    title=name,
                    url=app_url,
                    description_en=f"Ranked #{rank} in OpenRouter Global App Rankings. Weekly tokens: {tokens_raw}.",
                    metrics={
                        "tokens_week": tokens_raw,
                        "tokens_int": tokens_int,
                        "wow_pct": 0,
                        "section": "global",
                        "categories": cats,
                        "rank_global": rank,
                    },
                )
                items[app_url] = item

        # ── Category pages (agent / coding / productivity) ─────────────────────
        for cat_name, jina_url in CATEGORY_PAGES.items():
            try:
                cat_md = _fetch(jina_url)
                time.sleep(0.4)
            except Exception as e:
                log.warning("[openrouter] category %s failed: %s", cat_name, e)
                continue

            for m in CATEGORY_RE.finditer(cat_md):
                name, tokens_raw, slug = m.group(1).strip(), m.group(2), m.group(3)
                app_url = f"https://openrouter.ai/apps/{slug}"
                if app_url not in items:
                    item = SignalItem(
                        id=make_id("openrouter", app_url),
                        source="openrouter",
                        collected_at=now,
                        title=name,
                        url=app_url,
                        description_en=f"App in OpenRouter {cat_name} category. Tokens: {tokens_raw}.",
                        metrics={
                            "tokens_week": tokens_raw,
                            "tokens_int": _parse_tokens(tokens_raw),
                            "wow_pct": 0,
                            "section": f"category_{cat_name}",
                            "categories": [cat_name],
                            "rank_global": None,
                        },
                    )
                    items[app_url] = item
                else:
                    cats = items[app_url].metrics.setdefault("categories", [])
                    if cat_name not in cats:
                        cats.append(cat_name)

        result = list(items.values())
        log.info("[openrouter] %d apps (%d trending)", len(result), sum(1 for i in result if i.is_trending))
        return result
