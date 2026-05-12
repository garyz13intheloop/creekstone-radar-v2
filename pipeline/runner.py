"""
Master pipeline runner — full S1→S2→S3→store→Feishu chain.
Usage:
  python pipeline/runner.py                        # all sources, full pipeline
  python pipeline/runner.py --sources openrouter hackernews --no-enrich
  python pipeline/runner.py --weekly               # include Similarweb
"""
from __future__ import annotations
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from models.item import SignalItem, extract_domain
from pipeline.s1_filter import run_s1
from pipeline.s2_router import run_s2
from pipeline.s3_scorer import run_s3
from storage.store import save_daily, save_snapshot
from reports.feishu_daily import send_daily_brief
from enrichers.self_evolution import load_few_shots

log = logging.getLogger(__name__)


def _get_collectors() -> dict:
    from collectors.producthunt import ProductHuntCollector
    from collectors.github_trending import GitHubTrendingCollector
    from collectors.github_events import GitHubEventsCollector
    from collectors.arxiv_papers import ArxivCollector
    from collectors.hackernews import HackerNewsCollector
    from collectors.discord_monitor import DiscordCollector
    from collectors.reddit import RedditCollector
    from collectors.x_twitter import XTwitterCollector
    from collectors.openrouter_apps import OpenRouterAppsCollector
    from collectors.huggingface import HuggingFaceCollector
    return {
        "producthunt":     ProductHuntCollector,
        "github_trending": GitHubTrendingCollector,
        "github_events":   GitHubEventsCollector,
        "arxiv":           ArxivCollector,
        "hackernews":      HackerNewsCollector,
        "discord":         DiscordCollector,
        "reddit":          RedditCollector,
        "x_twitter":       XTwitterCollector,
        "openrouter":      OpenRouterAppsCollector,
        "huggingface":     HuggingFaceCollector,
    }


def run(
    sources: list[str] | None = None,
    skip_s2: bool = False,
    skip_s3: bool = False,
    skip_feishu: bool = False,
    run_similarweb: bool = False,
    date_str: str | None = None,
) -> list[SignalItem]:
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    active = sources or config.ENABLED_SOURCES
    collectors = _get_collectors()

    # ── Collect ────────────────────────────────────────────────────────────────
    raw_items: list[SignalItem] = []
    for src_id in active:
        cls = collectors.get(src_id)
        if not cls:
            log.warning("Unknown source: %s", src_id)
            continue
        items = cls().collect()
        raw_items.extend(items)

    log.info("Collected %d raw items from %d sources", len(raw_items), len(active))

    # ── S1: Hard filter ────────────────────────────────────────────────────────
    s1_passed, s1_dropped = run_s1(raw_items)
    log.info("S1: %d → %d (dropped %d)", len(raw_items), len(s1_passed), s1_dropped)

    # ── Cross-source dedup by domain ───────────────────────────────────────────
    seen_domains: dict[str, SignalItem] = {}  # domain → first (highest-signal) item
    domain_sources: dict[str, list[str]] = {}
    other_items: list[SignalItem] = []

    for item in s1_passed:
        domain = extract_domain(item.url)
        if not domain or domain in ("github.com", "producthunt.com", "x.com", "twitter.com"):
            other_items.append(item)  # can't dedup these by domain
            continue
        if domain not in seen_domains:
            seen_domains[domain] = item
            domain_sources[domain] = [item.source]
        else:
            # Merge: keep higher-signal item, accumulate sources
            domain_sources[domain].append(item.source)
            existing = seen_domains[domain]
            # Prefer PH/GitHub over Twitter for canonical URL
            source_priority = {"producthunt": 5, "github_trending": 4, "github_events": 4,
                                "hackernews": 3, "openrouter": 3, "x_twitter": 1}
            if source_priority.get(item.source, 2) > source_priority.get(existing.source, 2):
                seen_domains[domain] = item

    deduped: list[SignalItem] = list(seen_domains.values()) + other_items
    # Tag merged sources
    for domain, item in seen_domains.items():
        all_sources = domain_sources.get(domain, [])
        if len(all_sources) > 1:
            item.metrics["cross_sources"] = list(set(all_sources))

    log.info("After dedup: %d items", len(deduped))

    # ── S2: Track classification ───────────────────────────────────────────────
    if not skip_s2:
        s2_passed, s2_dropped = run_s2(deduped)
        log.info("S2: %d → %d (dropped %d)", len(deduped), len(s2_passed), s2_dropped)
    else:
        s2_passed = deduped
        for item in s2_passed:
            item.track = "unknown"

    # ── S3: Full scoring ───────────────────────────────────────────────────────
    if not skip_s3:
        s3_items = run_s3(s2_passed, few_shot_loader=load_few_shots)
    else:
        s3_items = s2_passed

    # ── Store ─────────────────────────────────────────────────────────────────
    save_daily(s3_items, date_str)
    for src_id in ("openrouter", "huggingface"):
        src_items = [i for i in s3_items if i.source == src_id]
        if src_items:
            save_snapshot(src_items, src_id, date_str)

    # ── Optional: Similarweb weekly run ───────────────────────────────────────
    if run_similarweb:
        from collectors.similarweb_monitor import run_weekly
        sw_result = run_weekly()
        if sw_result.get("spikes_detected"):
            for spike in sw_result["spikes_detected"]:
                log.info("[similarweb spike] %s +%.1f%%", spike["domain"], spike["mom_pct"])

    # ── Feishu push ───────────────────────────────────────────────────────────
    if not skip_feishu and config.FEISHU_WEBHOOK_URL:
        # Only push scored items with score > 0
        pushable = [i for i in s3_items if i.score > 40] if not skip_s3 else s3_items
        send_daily_brief(pushable)

    # ── Console summary ───────────────────────────────────────────────────────
    _print_summary(s3_items, date_str, skip_s3)
    return s3_items


def _print_summary(items: list[SignalItem], date_str: str, skip_s3: bool) -> None:
    by_src: dict[str, list] = {}
    by_track: dict[str, list] = {}
    for i in items:
        by_src.setdefault(i.source, []).append(i)
        by_track.setdefault(i.track, []).append(i)

    print(f"\n{'='*55}")
    print(f"  Creekstone Radar — {date_str}")
    print(f"{'='*55}")
    for src, src_items in sorted(by_src.items()):
        tr = sum(1 for i in src_items if i.is_trending)
        print(f"  {src:<22} {len(src_items):>3}  ({tr} trending)")
    print(f"{'─'*55}")
    print(f"  TOTAL: {len(items)} items")

    if not skip_s3:
        print(f"\n  Track distribution:")
        for track in ("A", "B", "C", "unknown"):
            ti = by_track.get(track, [])
            if ti:
                avg = sum(i.score for i in ti) / len(ti)
                print(f"  Track {track}: {len(ti)} items  avg score {avg:.1f}")

        top = sorted(items, key=lambda i: i.score, reverse=True)[:8]
        print(f"\n  Top 8 by score:")
        for i in top:
            flag = "🔥" if i.is_trending else "  "
            fde = f" FDE:{i.fde_index}" if i.track == "B" else ""
            print(f"  {flag} [{i.score:4.0f}] [Trk{i.track}]{fde} {i.title[:45]} ({i.source})")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Creekstone Radar v2")
    parser.add_argument("--sources", nargs="+", help="Specific sources to run")
    parser.add_argument("--no-s2", action="store_true", help="Skip Track classification")
    parser.add_argument("--no-s3", action="store_true", help="Skip LLM scoring")
    parser.add_argument("--no-feishu", action="store_true", help="Skip Feishu push")
    parser.add_argument("--weekly", action="store_true", help="Also run Similarweb")
    parser.add_argument("--date", help="Override date YYYY-MM-DD")
    args = parser.parse_args()

    run(
        sources=args.sources,
        skip_s2=args.no_s2,
        skip_s3=args.no_s3,
        skip_feishu=args.no_feishu,
        run_similarweb=args.weekly,
        date_str=args.date,
    )
