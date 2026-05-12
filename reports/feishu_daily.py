"""
Feishu daily brief — sends top signals to a Feishu webhook.
Format: Track-tagged cards with 3 action buttons each.
Buttons write to feedback.jsonl via a simple callback endpoint.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import config
from models.item import SignalItem
from storage.store import load_recent_daily

log = logging.getLogger(__name__)

FEISHU_WEBHOOK = config.FEISHU_WEBHOOK_URL   # add to config.py

TRACK_EMOJI = {"A": "🔵", "B": "🟢", "C": "🟡", "unknown": "⚪"}
TRACK_NAME = {"A": "框架", "B": "垂直FDE", "C": "A2A", "unknown": "未分类"}

MAX_REGULAR = 5
MAX_SPIKE = 2


def _format_metrics(item: SignalItem) -> str:
    m = item.metrics
    src = item.source
    if src == "producthunt":
        return f"PH ▲{m.get('votes', 0)}"
    if src in ("github_trending", "github_events"):
        s = m.get("stars", 0)
        sd = m.get("stars_today", m.get("stars_per_day", 0))
        return f"GitHub ⭐{s:,} +{sd}/日"
    if src == "openrouter":
        wow = m.get("wow_pct", 0)
        tok = m.get("tokens_week", "")
        return f"OpenRouter {tok} +{wow:.0f}% WoW"
    if src == "x_twitter":
        return f"X ❤{m.get('likes',0)} 🔖{m.get('bookmarks',0)}"
    if src == "hackernews":
        return f"HN {m.get('points',0)}pts {m.get('comments',0)}评"
    if src == "reddit":
        return f"r/{m.get('subreddit','')} ▲{m.get('upvotes',0)}"
    if src == "arxiv":
        return f"arXiv {'有代码' if m.get('has_github') else '纯论文'}"
    return src


def _build_item_block(item: SignalItem, rank: int) -> dict:
    """Build a Feishu card element for one signal item."""
    track_em = TRACK_EMOJI.get(item.track, "⚪")
    track_nm = TRACK_NAME.get(item.track, "")
    score_str = f"score {item.score:.0f}"
    fde_str = f" · FDE:{item.fde_index}" if item.track == "B" and item.fde_index > 0 else ""
    spike_str = " ⚡" if item.is_spike or (item.wow_growth_pct and item.wow_growth_pct > 200) else ""
    
    desc = item.description_zh or item.description_en[:100]
    metrics_str = _format_metrics(item)
    
    # Short URL display
    url_display = item.url[:60] + ("..." if len(item.url) > 60 else "")

    text = (
        f"{track_em} [{track_nm}] {item.title}{spike_str} · {score_str}{fde_str}\n"
        f"{desc}\n"
        f"{metrics_str} | {url_display}"
    )
    return {"tag": "div", "text": {"tag": "lark_md", "content": text}}


def _build_card(items: list[SignalItem], spike_items: list[SignalItem], date_str: str) -> dict:
    """Build the full Feishu card message."""
    elements: list[dict] = []

    # Header
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**📡 Creekstone Radar · {date_str}**\n"
                       f"今日信号 {len(items)} 条 | Track A:{sum(1 for i in items if i.track=='A')} "
                       f"B:{sum(1 for i in items if i.track=='B')} "
                       f"C:{sum(1 for i in items if i.track=='C')}"
        }
    })
    elements.append({"tag": "hr"})

    # Regular top items
    for rank, item in enumerate(items[:MAX_REGULAR], 1):
        elements.append(_build_item_block(item, rank))
        # Action buttons (feedback)
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "感兴趣"},
                    "type": "primary",
                    "value": {"action": "interested", "item_id": item.id, "title": item.title},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "忽略"},
                    "type": "default",
                    "value": {"action": "ignored", "item_id": item.id, "title": item.title},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "+ Watchlist"},
                    "type": "default",
                    "value": {"action": "watchlist", "item_id": item.id, "title": item.title},
                },
            ]
        })
        elements.append({"tag": "hr"})

    # Spike alerts
    if spike_items:
        spike_texts = []
        for s in spike_items[:MAX_SPIKE]:
            wow = s.wow_growth_pct or s.metrics.get("wow_pct", 0)
            spike_texts.append(f"⚡ **{s.title}** +{wow:.0f}% WoW | {s.url[:50]}")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**异常信号**\n" + "\n".join(spike_texts)
            }
        })

    return {
        "msg_type": "interactive",
        "card": {
            "elements": elements,
            "header": {
                "title": {"tag": "plain_text", "content": f"Creekstone Radar · {date_str}"},
                "template": "blue",
            }
        }
    }


def send_daily_brief(items: list[SignalItem]) -> bool:
    """
    Select top items and send to Feishu webhook.
    Returns True if successful.
    """
    if not FEISHU_WEBHOOK:
        log.warning("[feishu] no webhook URL configured")
        return False

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Separate spikes from regular items
    spike_items = [i for i in items if i.is_spike or (i.wow_growth_pct and i.wow_growth_pct > 200)]
    regular = [i for i in items if i not in spike_items]

    # Top regular: ensure at least 1 from each Track if possible, rest by score
    selected: list[SignalItem] = []
    for track in ("A", "B", "C"):
        track_items = [i for i in regular if i.track == track]
        if track_items:
            selected.append(max(track_items, key=lambda x: x.score))

    # Fill remaining slots by score
    remaining = [i for i in regular if i not in selected]
    remaining.sort(key=lambda x: x.score, reverse=True)
    selected.extend(remaining[:MAX_REGULAR - len(selected)])
    selected = selected[:MAX_REGULAR]
    selected.sort(key=lambda x: x.score, reverse=True)

    if not selected:
        log.info("[feishu] no items to send")
        return True

    card = _build_card(selected, spike_items, date_str)

    try:
        resp = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
        resp.raise_for_status()
        log.info("[feishu] sent %d items + %d spikes", len(selected), len(spike_items))
        return True
    except Exception as e:
        log.error("[feishu] send failed: %s", e)
        return False
