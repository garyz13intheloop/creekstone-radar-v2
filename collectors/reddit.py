"""
Reddit collector — monitors AI/Agent subreddits for new product launches.
Uses PRAW (Python Reddit API Wrapper). Requires free Reddit app credentials.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import config
from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

# Subreddits to monitor (curated for AI/Agent/startup discovery)
SUBREDDITS = [
    "LocalLLaMA",       # technical AI users — high signal quality
    "singularity",      # AI trends, new product launches
    "MachineLearning",  # research + product
    "SideProject",      # founders launching new products
    "ProductHunters",   # PH adjacent, many launches
    "artificial",       # general AI discussion
    "AIAgents",         # dedicated agent subreddit
    "ChatGPT",          # mass market AI usage signals
    "ClaudeAI",         # Claude/Anthropic ecosystem
    "LangChain",        # agent infra community
]

LAUNCH_KEYWORDS = [
    "launch", "released", "just built", "introducing", "open source",
    "github.com", "producthunt", "show reddit", "i made", "new tool",
    "agent", "mcp", "agentic", "llm", "ai tool"
]

MIN_UPVOTES = 20       # filter noise
LOOKBACK_HOURS = 48


class RedditCollector(BaseCollector):
    source_id = "reddit"

    def _get_praw(self):
        try:
            import praw
            return praw.Reddit(
                client_id=config.REDDIT_CLIENT_ID,
                client_secret=config.REDDIT_CLIENT_SECRET,
                user_agent=config.REDDIT_USER_AGENT,
                ratelimit_seconds=2,
            )
        except ImportError:
            log.error("[reddit] praw not installed: pip install praw")
            return None
        except Exception as e:
            log.error("[reddit] PRAW init failed: %s", e)
            return None

    def _collect(self) -> list[SignalItem]:
        if not config.REDDIT_CLIENT_ID or not config.REDDIT_CLIENT_SECRET:
            log.warning("[reddit] no credentials, skipping")
            return []

        reddit = self._get_praw()
        if not reddit:
            return []

        now = utcnow()
        cutoff_ts = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp()
        seen: set[str] = set()
        items: list[SignalItem] = []

        for sub_name in SUBREDDITS:
            try:
                subreddit = reddit.subreddit(sub_name)
                posts = list(subreddit.new(limit=50))
                time.sleep(0.5)
            except Exception as e:
                log.warning("[reddit] failed subreddit %s: %s", sub_name, e)
                continue

            for post in posts:
                if post.created_utc < cutoff_ts:
                    continue
                if post.id in seen:
                    continue
                seen.add(post.id)

                if post.score < MIN_UPVOTES:
                    continue

                title_lower = post.title.lower()
                text_lower = (post.selftext or "").lower()
                merged = f"{title_lower} {text_lower}"

                # Must match at least one launch keyword
                if not any(k in merged for k in LAUNCH_KEYWORDS):
                    continue

                # External URL or self-post URL
                url = post.url if not post.is_self else f"https://reddit.com{post.permalink}"
                reddit_url = f"https://reddit.com{post.permalink}"

                item = SignalItem(
                    id=make_id("reddit", reddit_url),
                    source="reddit",
                    collected_at=now,
                    title=post.title,
                    url=url,
                    description_en=(post.selftext or "")[:500],
                    is_trending=post.score > 500 or post.num_comments > 100,
                    metrics={
                        "upvotes": post.score,
                        "comments": post.num_comments,
                        "upvote_ratio": round(post.upvote_ratio, 2),
                        "subreddit": sub_name,
                        "reddit_url": reddit_url,
                        "created_utc": post.created_utc,
                        "author": str(post.author or "deleted"),
                        "is_self": post.is_self,
                        "flair": post.link_flair_text or "",
                    },
                )
                items.append(item)

        items.sort(key=lambda i: i.metrics.get("upvotes", 0), reverse=True)
        log.info("[reddit] %d qualifying posts from %d subreddits", len(items), len(SUBREDDITS))
        return items
