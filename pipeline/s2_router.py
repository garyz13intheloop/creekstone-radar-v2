"""
S2 — Track classification router.
Single cheap LLM call (gemini-flash) per item.
Outputs: track (A/B/C), fde_stage, confidence, relevant.
This context is injected into S3 for track-aware scoring.
"""
from __future__ import annotations
import json
import logging
import re
import time
from typing import Any

import requests

import config
from models.item import SignalItem, Track

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 Creekstone Ventures 的产品分类助手。
Creekstone 关注三个方向：

Track A — Agent 基础框架
被其他产品采用为依赖 / MCP兼容 / 模型无关 / 工具调度内存多Agent协作基础设施
代表：LangChain、OpenHands、Cursor SDK、Exa、CrewAI

Track B — 垂直 Agent / FDE化（Full Domain Expert）
在单一领域深度专注 / 积累领域私有数据 / 结果交付而非对话 / 停用即痛
代表：Harvey(法律)、Abridge(医疗)、Sierra(客服)、Glean(企业搜索)
FDE阶段: single_tool(0-3) → accumulating(4-6) → flywheel(7-8) → achieved(9-10)

Track C — Agent to Agent 网络（含软硬结合）
Agent间通信协议 / 发现注册 / 网络效应 / 硬件集成（机器人/IoT/物理执行器）

输出 JSON（不要额外说明）：
{
  "relevant": true,
  "track": "A",
  "track_reason": "一句话，不超过25字",
  "confidence": "high",
  "fde_stage": ""
}
confidence: high=明显符合某track / medium=基本符合 / low=不确定
fde_stage: 仅Track B填写，其他填""
relevant=false 时其他字段可空。"""


def _call_llm(item: SignalItem) -> dict[str, Any]:
    user_msg = (
        f"标题: {item.title}\n"
        f"来源: {item.source}\n"
        f"描述: {item.description_en[:600]}\n"
        f"指标: {_fmt_metrics(item)}"
    )

    resp = requests.post(
        f"{config.LLM_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.LLM_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://creekstone.vc",
            "X-Title": "CreekstoneRadarS2",
        },
        json={
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.1,
            "max_tokens": 120,
            "response_format": {"type": "json_object"},
        },
        timeout=20,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _fmt_metrics(item: SignalItem) -> str:
    m = item.metrics
    parts = []
    if item.source == "producthunt":
        parts.append(f"PH votes:{m.get('votes', 0)}")
    elif item.source in ("github_trending", "github_events"):
        parts.append(f"Stars:{m.get('stars', 0)} today:{m.get('stars_today', m.get('stars_per_day', 0))}")
    elif item.source == "openrouter":
        parts.append(f"Tokens:{m.get('tokens_week','')} WoW:+{m.get('wow_pct',0):.0f}%")
    elif item.source == "x_twitter":
        parts.append(f"Likes:{m.get('likes',0)} Bookmarks:{m.get('bookmarks',0)}")
    elif item.source == "hackernews":
        parts.append(f"HN points:{m.get('points',0)}")
    elif item.source == "reddit":
        parts.append(f"r/{m.get('subreddit','')} upvotes:{m.get('upvotes',0)}")
    return " | ".join(parts) if parts else "n/a"


def _apply_result(item: SignalItem, result: dict) -> bool:
    """Apply S2 result to item. Returns False if item should be dropped."""
    if not result.get("relevant", True):
        return False

    raw_track = str(result.get("track", "")).upper().strip()
    valid_tracks: dict[str, Track] = {"A": "A", "B": "B", "C": "C"}
    item.track = valid_tracks.get(raw_track, "unknown")
    item.track_reason = str(result.get("track_reason", ""))[:100]
    item.track_confidence = result.get("confidence", "low")

    if item.track == "B":
        item.fde_stage = result.get("fde_stage", "single_tool") or "single_tool"

    return True


def run_s2(
    items: list[SignalItem],
    skip_if_no_key: bool = True,
) -> tuple[list[SignalItem], int]:
    """
    Returns (passed_items, dropped_count).
    Low-confidence items are kept but flagged for human review.
    """
    if not config.LLM_API_KEY:
        if skip_if_no_key:
            log.warning("[S2] no LLM key, skipping (all items pass with track=unknown)")
            for item in items:
                item.track = "unknown"
                item.track_confidence = "low"
            return items, 0
        raise RuntimeError("LLM_API_KEY required for S2")

    passed: list[SignalItem] = []
    dropped = 0

    for item in items:
        try:
            result = _call_llm(item)
            keep = _apply_result(item, result)
            if keep:
                passed.append(item)
            else:
                dropped += 1
        except Exception as e:
            log.warning("[S2] failed for '%s': %s — keeping with unknown track", item.title[:40], e)
            item.track = "unknown"
            item.track_confidence = "low"
            passed.append(item)
        time.sleep(0.2)

    log.info("[S2] %d → %d (dropped %d irrelevant)", len(items), len(passed), dropped)
    return passed, dropped
