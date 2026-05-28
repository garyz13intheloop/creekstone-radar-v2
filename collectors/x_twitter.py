"""
X / Twitter collector v3 — Smart keyword generation.
AB混合模式：静态核心词库 + 动态关键词（基于昨日Top Items + AI热点）。
4类搜索策略：产品发布 / Build-in-public / 技术热词 / 大V内容。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from requests_oauthlib import OAuth1

import config
from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

LOOKBACK_HOURS = 26

# Set this to override lookback for backfill (YYYY-MM-DD)
BACKFILL_DATE: str | None = None
MAX_RESULTS_PER_QUERY = 50

# ── Static keyword core (always included) ────────────────────────────────────
STATIC_CORE_TERMS = [
    "AI agent", "MCP server", "MCP tool", "agentic", "LLM tool",
    "Claude Code", "Cursor", "vibe coding", "multi-agent",
    "agent workflow", "tool calling", "AI copilot",
]

STATIC_LAUNCH_PHRASES = [
    '"just launched"', '"we launched"', '"launching today"',
    '"shipped today"', '"now live"', '"introducing"',
]

STATIC_BUILD_TAGS = [
    "#buildinpublic", "#indiedev", "#shipitsaturday", '"Product Hunt"',
]

# Gary's key accounts to monitor (X usernames)
VIP_ACCOUNTS = [
    "sama", "karpathy", "ylecun", "GaryMarcus",
    "fchollet", "emollick", "swyx", "AnthropicAI",
    "OpenAI", "GoogleDeepMind", "gdb", "naval",
    "paulg", "jason", "dhh",
]

# ── Dynamic keyword cache ────────────────────────────────────────────────────
_DYNAMIC_KW_CACHE_FILE = config.EVOLUTION_DIR / "x_dynamic_keywords.json"


def _load_dynamic_keywords() -> list[str]:
    """Load yesterday's generated dynamic keywords from cache."""
    try:
        if _DYNAMIC_KW_CACHE_FILE.exists():
            data = json.loads(_DYNAMIC_KW_CACHE_FILE.read_text())
            # Only use if generated today or yesterday
            ts = data.get("generated_at", "")
            if ts:
                age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 3600
                if age_hours < 36:
                    return data.get("keywords", [])
    except Exception as e:
        log.debug("[x_twitter] dynamic kw load error: %s", e)
    return []


def generate_dynamic_keywords(top_items_titles: list[str], llm_api_key: str) -> list[str]:
    """
    LLM-generated X search terms based on yesterday's top items.
    Called externally (e.g. runner.py) after previous day's S3 completes.
    Returns list of 5-8 search terms.
    """
    if not llm_api_key or not top_items_titles:
        return []

    titles_str = "\n".join(f"- {t}" for t in top_items_titles[:10])
    prompt = f"""根据以下昨日AI/Agent领域热门项目，生成5-8个今天适合在X(Twitter)上搜索的关键词或短语，
用来发现新的AI产品发布和技术讨论。要求：
1. 英文，适合Twitter搜索语法
2. 聚焦AI/Agent/MCP/LLM工具方向
3. 包含1-2个当前最热的具体技术术语（从下面的项目名称中提取）
4. 不要太宽泛（避免"AI"单词），不要太窄（避免某个产品专有名词）

昨日热门项目：
{titles_str}

直接输出JSON数组，不要其他内容：["term1", "term2", ...]"""

    try:
        resp = requests.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {llm_api_key}", "Content-Type": "application/json"},
            json={
                "model": config.LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": 200,
            },
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        m = re.search(r"\[.*\]", content, re.S)
        if m:
            kws = json.loads(m.group(0))
            result = [str(k).strip() for k in kws if str(k).strip()][:8]
            # Cache
            _DYNAMIC_KW_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _DYNAMIC_KW_CACHE_FILE.write_text(json.dumps({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_titles": top_items_titles[:10],
                "keywords": result,
            }, ensure_ascii=False, indent=2))
            log.info("[x_twitter] dynamic keywords generated: %s", result)
            return result
    except Exception as e:
        log.warning("[x_twitter] dynamic keyword gen failed: %s", e)
    return []


def _build_queries(dynamic_keywords: list[str]) -> list[str]:
    """
    Build final search query list = static + dynamic keywords.
    Follows Twitter v2 search syntax.
    """
    # Merge static core + dynamic
    all_terms = list(STATIC_CORE_TERMS)
    for kw in dynamic_keywords:
        if kw not in all_terms:
            all_terms.append(kw)

    tech_terms_q = " OR ".join(f'"{t}"' if " " in t else t for t in all_terms[:12])
    launch_phrases_q = " OR ".join(STATIC_LAUNCH_PHRASES)
    build_tags_q = " OR ".join(STATIC_BUILD_TAGS)
    vip_from_q = " OR ".join(f"from:{u}" for u in VIP_ACCOUNTS[:10])

    queries = [
        # 1. Launch signal: launch phrase + tech term
        f"({launch_phrases_q}) ({tech_terms_q}) -is:retweet lang:en",

        # 2. Build-in-public + tech
        f"({build_tags_q}) ({tech_terms_q}) -is:retweet lang:en has:links",

        # 3. Demo videos with tech content
        f"({tech_terms_q}) -is:retweet lang:en has:videos has:links",

        # 4. GitHub + AI tools
        f'(github.com OR "open source") ({tech_terms_q}) -is:retweet lang:en has:links',

        # 5. VIP accounts content — monitor key voices
        f"({vip_from_q}) ({tech_terms_q}) -is:retweet lang:en",
    ]
    return queries


class XTwitterCollector(BaseCollector):
    source_id = "x_twitter"

    def __init__(self):
        self._auth = OAuth1(
            config.X_API_KEY,
            config.X_API_SECRET,
            config.X_ACCESS_TOKEN,
            config.X_ACCESS_TOKEN_SECRET,
        )

    def _search(self, query: str, max_results: int = MAX_RESULTS_PER_QUERY) -> tuple[list[dict], dict]:
        if BACKFILL_DATE:
            start_time = f"{BACKFILL_DATE}T00:00:00Z"
            end_time = f"{BACKFILL_DATE}T23:59:59Z"
        else:
            start_time = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            end_time = None
        params: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "start_time": start_time,
            "tweet.fields": "created_at,public_metrics,author_id,attachments,entities",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "username,name,public_metrics,verified",
            "media.fields": "type,duration_ms",
        }
        try:
            r = requests.get(
                "https://api.twitter.com/2/tweets/search/recent",
                auth=self._auth,
                params=params,
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            return data.get("data", []), data.get("includes", {})
        except Exception as e:
            log.warning("[x_twitter] search failed for '%s': %s", query[:60], e)
            return [], {}

    def _collect(self) -> list[SignalItem]:
        if not config.X_API_KEY:
            log.warning("[x_twitter] no credentials, skipping")
            return []

        now = utcnow()
        dynamic_keywords = _load_dynamic_keywords()
        queries = _build_queries(dynamic_keywords)

        seen_ids: set[str] = set()
        items: list[SignalItem] = []

        for q_idx, query in enumerate(queries):
            tweets, includes = self._search(query)
            time.sleep(1.5)  # rate-limit

            users = {u["id"]: u for u in includes.get("users", [])}
            media_map = {m.get("media_key", ""): m.get("type", "") for m in includes.get("media", [])}
            is_vip_query = q_idx == 4  # last query is VIP accounts

            for tweet in tweets:
                tweet_id = tweet["id"]
                if tweet_id in seen_ids:
                    continue
                seen_ids.add(tweet_id)

                metrics = tweet.get("public_metrics", {})
                likes = metrics.get("like_count", 0)
                bookmarks = metrics.get("bookmark_count", 0)
                retweets = metrics.get("retweet_count", 0)
                impressions = metrics.get("impression_count", 0)

                # VIP accounts have lower threshold
                min_likes = 5 if is_vip_query else config.X_MIN_LIKES
                if likes < min_likes and bookmarks < 3:
                    continue

                author_id = tweet.get("author_id", "")
                author = users.get(author_id, {})
                username = author.get("username", "unknown")
                author_metrics = author.get("public_metrics", {})

                text = tweet.get("text", "")
                created_at = tweet.get("created_at", now)

                tweet_url = f"https://x.com/{username}/status/{tweet_id}"
                urls = [
                    u.get("expanded_url", "")
                    for u in tweet.get("entities", {}).get("urls", [])
                    if u.get("expanded_url", "")
                    and "twitter.com" not in u.get("expanded_url", "")
                    and "t.co" not in u.get("expanded_url", "")
                ]
                product_url = urls[0] if urls else tweet_url

                media_keys = tweet.get("attachments", {}).get("media_keys", [])
                has_video = any(media_map.get(k, "") == "video" for k in media_keys)

                virality = likes * 1 + bookmarks * 3 + retweets * 2 + (impressions / 1000)
                is_trending = virality > 200 or impressions > 50000

                item = SignalItem(
                    id=make_id("x_twitter", tweet_url),
                    source="x_twitter",
                    collected_at=now,
                    title=_extract_title(text, username),
                    url=tweet_url,
                    description_en=text[:500],
                    is_trending=is_trending,
                    has_video=has_video,
                    metrics={
                        "likes": likes,
                        "retweets": retweets,
                        "bookmarks": bookmarks,
                        "impressions": impressions,
                        "replies": metrics.get("reply_count", 0),
                        "virality_score": round(virality, 1),
                        "username": username,
                        "author_followers": author_metrics.get("followers_count", 0),
                        "created_at": created_at,
                        "has_video": has_video,
                        "product_url": product_url,
                        "query_type": ["launch", "buildinpublic", "video", "github", "vip"][q_idx],
                        "is_vip_account": is_vip_query and username in VIP_ACCOUNTS,
                    },
                    raw={"full_text": text, "tweet_id": tweet_id},
                )
                items.append(item)

        items.sort(key=lambda i: i.metrics.get("virality_score", 0), reverse=True)
        log.info("[x_twitter] %d items from %d queries (dynamic kws: %d)", len(items), len(queries), len(dynamic_keywords))
        return items


def _extract_title(text: str, username: str) -> str:
    first_line = text.split("\n")[0]
    first_line = re.sub(r"https?://\S+", "", first_line).strip()
    first_line = re.sub(r"@\w+", "", first_line).strip()
    if len(first_line) > 80:
        first_line = first_line[:77] + "..."
    return first_line or f"Tweet by @{username}"
