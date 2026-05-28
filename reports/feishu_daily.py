"""
Feishu daily brief v3.
7 Tracks: A/B/C/Hardware/Tech/Multimodal/Lifestyle.
Per-track cards + "跟进" / "忽略" buttons.
"跟进" → auto-sync to Bitable sourcing table.
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

FEISHU_WEBHOOK = config.FEISHU_WEBHOOK_URL

# Bitable sourcing table config (set in .env)
BITABLE_APP_TOKEN: str = config.__dict__.get("BITABLE_APP_TOKEN", "") or __import__("os").getenv("BITABLE_APP_TOKEN", "")
BITABLE_TABLE_ID: str = config.__dict__.get("BITABLE_TABLE_ID", "") or __import__("os").getenv("BITABLE_TABLE_ID", "")
FEISHU_APP_ID: str = __import__("os").getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET: str = __import__("os").getenv("FEISHU_APP_SECRET", "")

MAX_PER_TRACK = 3        # max items per track in daily push
MAX_TRACKS_IN_PUSH = 5  # max tracks shown (top by score)

TRACK_EMOJI = {
    "A": "🔵", "B": "🟢", "C": "🟡",
    "Hardware": "🔩", "Tech": "🔬",
    "Multimodal": "🎬", "Lifestyle": "💜",
    "unknown": "⚪",
}
TRACK_NAME = {
    "A": "框架 & 效率", "B": "垂直FDE", "C": "A2A",
    "Hardware": "硬件层", "Tech": "技术突破",
    "Multimodal": "多模态", "Lifestyle": "生活 & 陪伴",
    "unknown": "未分类",
}

SOURCE_LABEL = {
    "producthunt": "PH", "github_trending": "GitHub", "github_events": "GitHub",
    "arxiv": "arXiv", "hackernews": "HN", "x_twitter": "X",
    "openrouter": "OR", "huggingface": "HF", "reddit": "Reddit",
    "similarweb": "SW",
}


def _fmt_metrics(item: SignalItem) -> str:
    m = item.metrics
    src = item.source
    parts = []
    if src == "producthunt":
        parts.append(f"PH ▲{m.get('votes', 0)}")
    elif src in ("github_trending", "github_events"):
        s = m.get("stars", 0)
        sd = m.get("stars_today", m.get("stars_per_day", 0))
        if s:
            parts.append(f"⭐{s:,} +{sd}/day")
    elif src == "openrouter":
        wow = m.get("wow_pct", 0)
        parts.append(f"OR +{wow:.0f}% WoW")
    elif src == "x_twitter":
        parts.append(f"❤{m.get('likes',0)} 🔖{m.get('bookmarks',0)}")
    elif src == "hackernews":
        parts.append(f"HN {m.get('points',0)}pts")
    elif src == "arxiv":
        parts.append("arXiv")
    if item.score > 0:
        parts.append(f"Score **{item.score:.0f}**")
    return " · ".join(parts)


def _item_block(item: SignalItem, rank: int) -> list[dict]:
    """Build Feishu card elements for one item."""
    elements = []

    # Title + one-liner
    one_liner = ""
    if item.full_profile and item.full_profile.one_liner:
        one_liner = item.full_profile.one_liner
    elif item.description_zh:
        one_liner = item.description_zh[:80]

    metrics_str = _fmt_metrics(item)
    src_label = SOURCE_LABEL.get(item.source, item.source)

    header_text = f"**{rank}. {item.title}**\n{one_liner}\n{metrics_str} | `{src_label}` | [链接]({item.url})"

    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": header_text}
    })

    # Score narrative (if available)
    if item.full_profile and item.full_profile.score_narrative_zh:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"_{item.full_profile.score_narrative_zh}_"}
        })

    # Action buttons
    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "跟进"},
                "type": "primary",
                "value": {
                    "action": "follow_up",
                    "item_id": item.id,
                    "title": item.title,
                    "url": item.url,
                    "track": item.track,
                    "score": item.score,
                },
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
    return elements


def _build_message(items_by_track: dict[str, list[SignalItem]], date_str: str, total: int) -> dict:
    """Build full Feishu interactive card."""
    elements: list[dict] = []

    # Summary header
    track_counts = " · ".join(
        f"{TRACK_EMOJI.get(t,'⚪')}{TRACK_NAME.get(t,t)} {len(v)}"
        for t, v in items_by_track.items()
        if v
    )
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": (
                f"**📡 Creekstone Radar · {date_str}**\n"
                f"今日收录 **{total}** 条信号 · 精选推送\n"
                f"{track_counts}"
            )
        }
    })
    elements.append({"tag": "hr"})

    # Per-track sections
    for track, track_items in items_by_track.items():
        if not track_items:
            continue
        emoji = TRACK_EMOJI.get(track, "⚪")
        name = TRACK_NAME.get(track, track)
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**{emoji} Track {track} — {name}**"}
        })
        for rank, item in enumerate(track_items[:MAX_PER_TRACK], 1):
            elements.extend(_item_block(item, rank))

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


def _get_feishu_token() -> str:
    """Get Feishu tenant access token for Bitable API."""
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        return ""
    try:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("tenant_access_token", "")
    except Exception as e:
        log.error("[feishu] get token failed: %s", e)
        return ""


def sync_to_bitable(item: SignalItem) -> bool:
    """
    Sync a follow_up item to Feishu Bitable sourcing table.
    Called when Gary clicks "跟进" in Feishu or web UI.
    """
    if not BITABLE_APP_TOKEN or not BITABLE_TABLE_ID:
        log.warning("[feishu] Bitable not configured (BITABLE_APP_TOKEN / BITABLE_TABLE_ID missing)")
        return False

    token = _get_feishu_token()
    if not token:
        return False

    # Build record fields
    profile = item.full_profile
    team = item.team

    fields: dict[str, Any] = {
        "项目名称": item.title,
        "URL": item.url,
        "来源": SOURCE_LABEL.get(item.source, item.source),
        "Track": f"{TRACK_EMOJI.get(item.track,'')} {item.track}",
        "评分": item.score,
        "一句话介绍": profile.one_liner if profile else item.description_zh[:100],
        "核心摘要": profile.overview_zh if profile else "",
        "商业模式": profile.biz_model_zh if profile else "",
        "Creekstone视角": profile.insight_zh if profile else "",
        "评分逻辑": profile.score_narrative_zh if profile else "",
        "数据指标": profile.metrics_summary if profile else "",
        "关键词": ", ".join(item.keywords),
        "Founder信息": (team.notes if team else "") or (profile.founder_detail if profile else ""),
        "融资信息": (team.funding_info if team else "") or (profile.funding_rounds if profile else ""),
        "是否华人创始人": "是" if (team and team.is_chinese_heritage) else "待确认",
        "收录日期": item.collected_at[:10],
        "状态": "待跟进",
        "来源原始ID": item.id,
    }

    # Add score breakdown
    if item.score_breakdown:
        sb = item.score_breakdown
        fields["评分明细"] = (
            f"AI Native:{sb.ai_native}/30 · Niche:{sb.niche}/25 · "
            f"商业:{sb.business}/20 · 团队:{sb.team}/15 · "
            f"加分:{sb.bonus} 减分:{sb.penalty}"
        )

    try:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records"
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"fields": fields},
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 0:
            log.info("[feishu] Bitable sync OK: %s", item.title[:40])
            return True
        else:
            log.error("[feishu] Bitable sync error: %s", result)
            return False
    except Exception as e:
        log.error("[feishu] Bitable sync failed: %s", e)
        return False


def send_daily_brief(items: list[SignalItem]) -> bool:
    """Select top items per track and send to Feishu webhook."""
    if not FEISHU_WEBHOOK:
        log.warning("[feishu] no webhook URL configured")
        return False

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = len(items)

    # Group by track, sorted by score
    track_order = ["A", "B", "C", "Hardware", "Multimodal", "Tech", "Lifestyle", "unknown"]
    items_by_track: dict[str, list[SignalItem]] = {}
    for track in track_order:
        track_items = sorted(
            [i for i in items if i.track == track],
            key=lambda x: x.score, reverse=True
        )
        if track_items:
            items_by_track[track] = track_items[:MAX_PER_TRACK]

    # Limit total tracks in push
    if len(items_by_track) > MAX_TRACKS_IN_PUSH:
        # Keep tracks with highest avg score
        track_avgs = {t: sum(i.score for i in v) / len(v) for t, v in items_by_track.items()}
        top_tracks = sorted(track_avgs, key=lambda t: track_avgs[t], reverse=True)[:MAX_TRACKS_IN_PUSH]
        items_by_track = {t: items_by_track[t] for t in track_order if t in top_tracks}

    if not items_by_track:
        log.info("[feishu] no items to send")
        return True

    message = _build_message(items_by_track, date_str, total)

    try:
        resp = requests.post(FEISHU_WEBHOOK, json=message, timeout=10)
        resp.raise_for_status()
        sent_count = sum(len(v) for v in items_by_track.values())
        log.info("[feishu] sent %d items across %d tracks", sent_count, len(items_by_track))
        return True
    except Exception as e:
        log.error("[feishu] send failed: %s", e)
        return False
