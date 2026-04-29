"""
LLM enricher — single call per item to fill:
  - description_zh (Chinese summary)
  - keywords (5-8 items)
  - score (0-10 investment relevance)

Uses OpenRouter (OpenAI-compatible) for cost efficiency.
Batches items to minimize API calls.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

import config
from models.item import SignalItem

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 Creekstone Ventures 的 AI 研究助手，专注于 Agent、Agent Infra、Personal Agent、多模态 AI 产品的早期投资机会识别。

对每个产品，用 JSON 格式输出：
{
  "summary_zh": "2-3句中文介绍：产品做什么、目标用户、核心技术",
  "keywords": ["关键词1", ..., "关键词6"],
  "score": 7.2,
  "score_reason": "一句话评分理由"
}

评分标准 (0-10):
- 9-10: 颠覆性，Agent/Infra 核心，增长极快
- 7-8:  清晰产品，AI-native，有实际用户
- 5-6:  方向对但差异化不足
- 3-4:  普通 AI 包装，无核心壁垒
- 1-2:  噪音，与 Agent/AI 产品无关
"""

USER_PROMPT_TEMPLATE = """产品信息：
标题: {title}
来源: {source}
描述 (EN): {description}
指标: {metrics_summary}

请用 JSON 格式输出分析。"""


def _metrics_summary(item: SignalItem) -> str:
    m = item.metrics
    parts: list[str] = []

    if item.source == "producthunt":
        parts.append(f"PH votes: {m.get('votes', 0)}")
    elif item.source in ("github_trending", "github_events"):
        parts.append(f"Stars: {m.get('stars', 0)}, Stars/day: {m.get('stars_today', m.get('stars_per_day', 0))}")
    elif item.source == "openrouter":
        parts.append(f"Tokens/week: {m.get('tokens_week', '')}, WoW: +{m.get('wow_pct', 0):.0f}%")
        if m.get("categories"):
            parts.append(f"Categories: {', '.join(m['categories'])}")
    elif item.source == "x_twitter":
        parts.append(f"Likes: {m.get('likes', 0)}, Bookmarks: {m.get('bookmarks', 0)}, Impressions: {m.get('impressions', 0)}")
        if m.get("has_video"):
            parts.append("Has demo video")
    elif item.source == "reddit":
        parts.append(f"Upvotes: {m.get('upvotes', 0)}, Comments: {m.get('comments', 0)}, Subreddit: r/{m.get('subreddit', '')}")
    elif item.source == "hackernews":
        parts.append(f"HN points: {m.get('points', 0)}, Comments: {m.get('comments', 0)}")
    elif item.source == "huggingface":
        parts.append(f"Downloads: {m.get('downloads', 0):,}, Likes: {m.get('likes', 0)}, Type: {m.get('type', '')}")

    return "; ".join(parts) if parts else "N/A"


def enrich_items(items: list[SignalItem]) -> list[SignalItem]:
    """Enrich a list of items with LLM summaries, keywords, scores."""
    if not config.LLM_API_KEY:
        log.warning("[enricher] no LLM API key, skipping enrichment")
        return items

    for i, item in enumerate(items):
        try:
            _enrich_one(item)
            if (i + 1) % 10 == 0:
                log.info("[enricher] enriched %d/%d", i + 1, len(items))
            time.sleep(0.3)  # gentle rate limit
        except Exception as e:
            log.error("[enricher] failed for %s: %s", item.title[:40], e)

    return items


def _enrich_one(item: SignalItem) -> None:
    user_msg = USER_PROMPT_TEMPLATE.format(
        title=item.title,
        source=item.source,
        description=(item.description_en or "")[:800],
        metrics_summary=_metrics_summary(item),
    )

    resp = requests.post(
        f"{config.LLM_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.LLM_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://creekstone.vc",
            "X-Title": "CreekstoneRadar",
        },
        json={
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.3,
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
        },
        timeout=config.LLM_TIMEOUT,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    try:
        result: dict[str, Any] = json.loads(content)
    except json.JSONDecodeError:
        # Fallback: try to extract JSON block
        import re
        m = re.search(r"\{.*\}", content, re.S)
        result = json.loads(m.group(0)) if m else {}

    item.description_zh = str(result.get("summary_zh", ""))[:500]
    raw_keywords = result.get("keywords", [])
    item.keywords = [str(k).strip() for k in raw_keywords if str(k).strip()][:8]
    try:
        item.score = round(float(result.get("score", 0)), 1)
    except (TypeError, ValueError):
        item.score = 0.0
