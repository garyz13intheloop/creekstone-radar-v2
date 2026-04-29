"""
Pipeline runner — orchestrates: collect → dedup → enrich → store.
Can be run for specific sources or all enabled sources.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow importing from project root
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from models.item import SignalItem
from enrichers.llm_enricher import enrich_items
from storage.store import save_daily, save_snapshot

log = logging.getLogger(__name__)

# Source registry
def _get_collectors():
    from collectors.producthunt import ProductHuntCollector
    from collectors.github_trending import GitHubTrendingCollector
    from collectors.github_events import GitHubEventsCollector
    from collectors.hackernews import HackerNewsCollector
    from collectors.openrouter_apps import OpenRouterAppsCollector
    from collectors.huggingface import HuggingFaceCollector
    from collectors.x_twitter import XTwitterCollector
    from collectors.reddit import RedditCollector

    return {
        "producthunt": ProductHuntCollector,
        "github_trending": GitHubTrendingCollector,
        "github_events": GitHubEventsCollector,
        "hackernews": HackerNewsCollector,
        "openrouter": OpenRouterAppsCollector,
        "huggingface": HuggingFaceCollector,
        "x_twitter": XTwitterCollector,
        "reddit": RedditCollector,
    }


def run(
    sources: list[str] | None = None,
    skip_enrichment: bool = False,
    date_str: str | None = None,
) -> list[SignalItem]:
    """
    Main pipeline entry point.
    
    Args:
        sources: list of source IDs to run, defaults to config.ENABLED_SOURCES
        skip_enrichment: skip LLM enrichment (faster, for testing)
        date_str: override date for storage (defaults to today UTC)
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    active_sources = sources or config.ENABLED_SOURCES
    collectors = _get_collectors()

    # ── Collect ────────────────────────────────────────────────────────────────
    all_items: list[SignalItem] = []
    for source_id in active_sources:
        cls = collectors.get(source_id)
        if cls is None:
            log.warning("Unknown source: %s", source_id)
            continue
        collector = cls()
        items = collector.collect()
        all_items.extend(items)

    log.info("Collected %d total items from %d sources", len(all_items), len(active_sources))

    # ── Cross-source dedup by URL ──────────────────────────────────────────────
    seen_urls: set[str] = set()
    deduped: list[SignalItem] = []
    for item in all_items:
        norm_url = item.url.rstrip("/").lower()
        if norm_url not in seen_urls:
            seen_urls.add(norm_url)
            deduped.append(item)

    log.info("After dedup: %d items", len(deduped))

    # ── Enrich ────────────────────────────────────────────────────────────────
    if not skip_enrichment:
        # Only enrich items with meaningful content (skip empty descriptions)
        to_enrich = [i for i in deduped if i.description_en or i.title]
        enrich_items(to_enrich)

    # ── Store ─────────────────────────────────────────────────────────────────
    save_daily(deduped, date_str)

    # Save weekly snapshots for growth tracking (OpenRouter + HuggingFace)
    for source_id in ("openrouter", "huggingface"):
        source_items = [i for i in deduped if i.source == source_id]
        if source_items:
            save_snapshot(source_items, source_id, date_str)

    # ── Summary ───────────────────────────────────────────────────────────────
    by_source = {}
    for item in deduped:
        by_source.setdefault(item.source, []).append(item)

    print(f"\n{'='*50}")
    print(f"Creekstone Radar — {date_str}")
    print(f"{'='*50}")
    for src, src_items in sorted(by_source.items()):
        trending = sum(1 for i in src_items if i.is_trending)
        print(f"  {src:<20} {len(src_items):>3} items  ({trending} trending)")
    print(f"{'='*50}")
    print(f"  TOTAL: {len(deduped)} items\n")

    # Top picks by score
    top = sorted(deduped, key=lambda i: i.score, reverse=True)[:10]
    if top and not skip_enrichment:
        print("Top 10 by score:")
        for i, item in enumerate(top, 1):
            flag = "🔥" if item.is_trending else "  "
            print(f"  {i:>2}. {flag} [{item.score}] {item.title[:50]} ({item.source})")
    print()

    return deduped


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    import argparse
    parser = argparse.ArgumentParser(description="Creekstone Radar v2 Pipeline")
    parser.add_argument("--sources", nargs="+", help="Specific sources to run")
    parser.add_argument("--no-enrich", action="store_true", help="Skip LLM enrichment")
    parser.add_argument("--date", help="Override date (YYYY-MM-DD)")
    args = parser.parse_args()

    run(
        sources=args.sources,
        skip_enrichment=args.no_enrich,
        date_str=args.date,
    )
