"""
Discord collector — listens to release/launch channels in key AI servers.
Requires a Discord bot token and manual server join.

Setup:
1. Create bot at discord.com/developers/applications
2. Enable: Message Content Intent (in Bot settings)
3. Add bot to target servers with Read Messages permission
4. Set DISCORD_BOT_TOKEN in .env

For GitHub Actions: runs as a one-shot scraper, not persistent listener.
Uses discord.py's fetch_channel_history approach.
"""
from __future__ import annotations
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import config
from collectors.base import BaseCollector, utcnow
from models.item import SignalItem, make_id

log = logging.getLogger(__name__)

# Target servers and channels: {server_id: [channel_id, ...]}
# Gary must manually join these servers with the bot
MONITORED_CHANNELS: dict[int, list[int]] = {
    # Format: server_id: [channel_id, ...]
    # Add real IDs after bot is in the servers
    # Example:
    # 879548655 (HuggingFace): [releases_channel_id, announcements_channel_id]
    # 1012345678 (LangChain): [releases_channel_id]
}

# Auto-discover channel names matching these patterns
CHANNEL_NAME_PATTERNS = [
    "release", "launch", "announcement", "show-case", "showcase",
    "new-tool", "product", "ship", "built"
]

LAUNCH_KEYWORDS = {
    "launched", "released", "introducing", "just shipped", "open source",
    "github.com", "producthunt", "new tool", "new agent", "mcp server",
    "we built", "i built", "check out", "try it",
}

LOOKBACK_HOURS = 48
MIN_REACTIONS = 3


class DiscordCollector(BaseCollector):
    source_id = "discord"

    def _collect(self) -> list[SignalItem]:
        token = config.DISCORD_BOT_TOKEN
        if not token:
            log.warning("[discord] no bot token, skipping")
            return []
        if not MONITORED_CHANNELS:
            log.warning("[discord] no monitored channels configured, skipping")
            return []

        try:
            import discord
        except ImportError:
            log.error("[discord] discord.py not installed: pip install discord.py")
            return []

        # Run async collection in sync context
        return asyncio.run(self._async_collect(token))

    async def _async_collect(self, token: str) -> list[SignalItem]:
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        results: list[SignalItem] = []
        now_str = utcnow()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

        @client.event
        async def on_ready():
            try:
                for guild_id, channel_ids in MONITORED_CHANNELS.items():
                    guild = client.get_guild(guild_id)
                    if not guild:
                        log.warning("[discord] guild %d not found", guild_id)
                        continue

                    # If no explicit channel IDs, auto-discover by name pattern
                    target_channels = channel_ids or [
                        ch.id for ch in guild.text_channels
                        if any(p in ch.name.lower() for p in CHANNEL_NAME_PATTERNS)
                    ]

                    for ch_id in target_channels:
                        channel = guild.get_channel(ch_id)
                        if not channel:
                            continue
                        try:
                            async for msg in channel.history(after=cutoff, limit=100):
                                item = _msg_to_item(msg, guild.name, now_str)
                                if item:
                                    results.append(item)
                        except Exception as e:
                            log.warning("[discord] channel %d error: %s", ch_id, e)
            finally:
                await client.close()

        await client.start(token)
        log.info("[discord] %d items from Discord", len(results))
        return results


def _msg_to_item(msg, server_name: str, now: str) -> Optional[SignalItem]:
    content = msg.content or ""
    content_lower = content.lower()

    # Must have launch keywords
    if not any(kw in content_lower for kw in LAUNCH_KEYWORDS):
        return None

    # Must have minimum reactions
    total_reactions = sum(r.count for r in msg.reactions) if msg.reactions else 0
    if total_reactions < MIN_REACTIONS:
        return None

    # Extract URLs
    import re
    urls = re.findall(r"https?://[^\s>]+", content)
    product_url = next(
        (u for u in urls if "github.com" in u or "producthunt.com" not in u),
        urls[0] if urls else f"https://discord.com/channels/{msg.guild.id}/{msg.channel.id}/{msg.id}"
    )

    discord_link = f"https://discord.com/channels/{msg.guild.id}/{msg.channel.id}/{msg.id}"

    return SignalItem(
        id=make_id("discord", discord_link),
        source="discord",
        collected_at=now,
        title=content[:120].replace("\n", " "),
        url=product_url,
        description_en=content[:500],
        is_trending=total_reactions >= 20,
        metrics={
            "reactions": total_reactions,
            "server": server_name,
            "channel": str(msg.channel.name),
            "author": str(msg.author),
            "discord_link": discord_link,
            "created_at": msg.created_at.isoformat(),
        },
    )
