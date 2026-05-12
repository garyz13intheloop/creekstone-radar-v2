"""
Similarweb parallel traffic monitor.
INDEPENDENT from daily pipeline. Runs weekly (Mondays).
Two tasks:
  1. New traffic tracking: first-time traffic snapshot for recently discovered products
  2. Old product spike detection: MoM growth >= 40% on watchlist domains

Uses Scrape.do to avoid expensive Similarweb API subscription.
Results stored in data/traffic/ — never blocks the main pipeline.
"""
from __future__ import annotations
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

import config

log = logging.getLogger(__name__)

SCRAPE_DO_TOKEN = config.SCRAPE_DO_TOKEN  # add to config.py
TRAFFIC_DIR = config.DATA_DIR / "traffic"
TRAFFIC_DIR.mkdir(parents=True, exist_ok=True)

MOM_SPIKE_THRESHOLD = 0.40   # 40% month-over-month growth triggers alert
MAX_DOMAINS_PER_RUN = 300    # Scrape.do cost control


def _scrape_similarweb(domain: str) -> Optional[dict]:
    """Scrape Similarweb traffic page for a domain."""
    url = f"https://www.similarweb.com/website/{domain}/"
    encoded = requests.utils.quote(url, safe="")
    scrape_url = f"https://api.scrape.do/?token={SCRAPE_DO_TOKEN}&url={encoded}&render=true"

    try:
        resp = requests.get(scrape_url, timeout=30)
        resp.raise_for_status()
        html = resp.text

        # Extract total visits
        visits = _extract_visits(html)
        mom = _extract_mom_growth(html)
        country = _extract_top_country(html)

        if visits is None:
            return None

        return {
            "domain": domain,
            "total_visits": visits,
            "mom_growth_pct": mom,
            "top_country": country,
            "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m"),
        }
    except Exception as e:
        log.warning("[similarweb] scrape failed for %s: %s", domain, e)
        return None


def _extract_visits(html: str) -> Optional[int]:
    # Pattern: data inside JSON or visible text like "1.2M" "850K" "12.3B"
    patterns = [
        r'"totalVisits"\s*:\s*([\d.]+(?:[TBMK])?)',
        r'Total Visits[^>]*>([\d.,]+(?:\s*[TBMK])?)',
        r'"visits"\s*:\s*([\d.]+)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            return _parse_sweb_number(m.group(1))
    return None


def _extract_mom_growth(html: str) -> float:
    patterns = [
        r'"momChange"\s*:\s*(-?[\d.]+)',
        r'Month.*?(\+?-?[\d.]+)%',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            try:
                return float(m.group(1).replace("+", "")) / 100
            except ValueError:
                pass
    return 0.0


def _extract_top_country(html: str) -> str:
    m = re.search(r'"topCountry"\s*:\s*"([^"]+)"', html, re.I)
    return m.group(1) if m else ""


def _parse_sweb_number(raw: str) -> Optional[int]:
    raw = raw.strip().upper().replace(",", "").replace(" ", "")
    m = re.match(r"([\d.]+)([TBMK]?)", raw)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}.get(m.group(2), 1)
    return int(v * mult)


def _load_watchlist() -> list[str]:
    """Load domain watchlist from storage."""
    wl_path = config.DATA_DIR / "watchlist.json"
    if not wl_path.exists():
        return []
    try:
        data = json.loads(wl_path.read_text(encoding="utf-8"))
        return [str(d).strip().lower() for d in data if d]
    except Exception:
        return []


def _load_recent_domains(days: int = 14) -> list[str]:
    """Extract domains from recently collected items (new product tracking)."""
    from storage.store import load_recent_daily
    items = load_recent_daily(days=days)
    domains: set[str] = set()
    for item in items:
        url = item.get("url", "")
        from models.item import extract_domain
        d = extract_domain(url)
        if d and "github.com" not in d and "producthunt.com" not in d:
            domains.add(d)
    return list(domains)[:MAX_DOMAINS_PER_RUN]


def _load_previous_snapshot(domain: str) -> Optional[dict]:
    """Load most recent snapshot for a domain for MoM comparison."""
    files = sorted(TRAFFIC_DIR.glob(f"*.json"), reverse=True)
    for f in files:
        try:
            records = json.loads(f.read_text(encoding="utf-8"))
            for r in records:
                if r.get("domain") == domain:
                    return r
        except Exception:
            pass
    return None


def _save_snapshots(snapshots: list[dict]) -> None:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = TRAFFIC_DIR / f"traffic_{date_str}.json"
    out_path.write_text(
        json.dumps(snapshots, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    log.info("[similarweb] saved %d snapshots → %s", len(snapshots), out_path.name)


def run_weekly() -> dict:
    """
    Main entry point for weekly Similarweb run.
    Returns summary dict with spike alerts.
    """
    if not SCRAPE_DO_TOKEN:
        log.warning("[similarweb] no SCRAPE_DO_TOKEN, skipping")
        return {"skipped": True}

    # Combine watchlist + recently seen domains
    watchlist = _load_watchlist()
    recent = _load_recent_domains(days=14)
    all_domains = list(dict.fromkeys(watchlist + recent))[:MAX_DOMAINS_PER_RUN]

    log.info("[similarweb] processing %d domains", len(all_domains))

    snapshots: list[dict] = []
    spikes: list[dict] = []   # MoM > 40%

    for domain in all_domains:
        snap = _scrape_similarweb(domain)
        if not snap:
            time.sleep(0.5)
            continue

        # Compare with previous snapshot for spike detection
        prev = _load_previous_snapshot(domain)
        if prev:
            prev_visits = prev.get("total_visits", 0)
            curr_visits = snap["total_visits"]
            if prev_visits > 0:
                computed_mom = (curr_visits - prev_visits) / prev_visits
                snap["mom_growth_pct"] = computed_mom
                if computed_mom >= MOM_SPIKE_THRESHOLD:
                    snap["is_spike"] = True
                    spikes.append({
                        "domain": domain,
                        "prev_visits": prev_visits,
                        "curr_visits": curr_visits,
                        "mom_pct": round(computed_mom * 100, 1),
                    })
        else:
            snap["is_new_domain"] = True   # first time tracking

        snapshots.append(snap)
        time.sleep(1.0)   # Scrape.do rate limit

    _save_snapshots(snapshots)

    result = {
        "total_domains": len(all_domains),
        "snapshots_taken": len(snapshots),
        "spikes_detected": spikes,
    }
    log.info("[similarweb] done. spikes: %d", len(spikes))
    return result


def get_traffic_for_domain(domain: str) -> Optional[dict]:
    """Lookup most recent traffic data for a domain (used by web dashboard)."""
    return _load_previous_snapshot(domain)
