"""
Weekly Intelligence Brief generator.
Reads last 7 days of NDJSON data and generates a Markdown report.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import config
from storage.store import load_recent_daily

log = logging.getLogger(__name__)

SOURCE_EMOJI = {
    "producthunt": "🚀",
    "github_trending": "⭐",
    "github_events": "📈",
    "hackernews": "🟠",
    "openrouter": "🤖",
    "huggingface": "🤗",
    "x_twitter": "𝕏",
    "reddit": "🔴",
}


def generate_weekly_brief(date_str: str | None = None) -> Path:
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    items = load_recent_daily(days=7)
    if not items:
        log.warning("No items found for weekly brief")
        return config.REPORTS_DIR / f"weekly_{date_str}.md"

    # Group by source and sort by score
    by_source = defaultdict(list)
    for item in items:
        by_source[item["source"]].append(item)

    for src in by_source:
        by_source[src].sort(key=lambda x: x.get("score", 0), reverse=True)

    # Top trending items (score ≥ 7, is_trending=True)
    top_trending = sorted(
        [i for i in items if i.get("is_trending") and i.get("score", 0) >= 6],
        key=lambda x: x.get("score", 0),
        reverse=True
    )[:20]

    # New products (is_new=True)
    new_products = sorted(
        [i for i in items if i.get("is_new")],
        key=lambda x: x.get("score", 0),
        reverse=True
    )[:15]

    # OpenRouter trending apps
    or_trending = sorted(
        [i for i in items if i["source"] == "openrouter" and i.get("metrics", {}).get("wow_pct", 0) > 50],
        key=lambda x: x.get("metrics", {}).get("wow_pct", 0),
        reverse=True
    )[:10]

    # Build report
    lines: list[str] = [
        f"# Creekstone Intelligence Brief — Week of {date_str}",
        "",
        f"> 数据来源：{len(items)} 条信号 · {len(set(i['source'] for i in items))} 个数据源 · 过去 7 天",
        "",
        "---",
        "",
    ]

    # Section 1: OpenRouter Trending (用量层信号)
    if or_trending:
        lines += [
            "## 🤖 OpenRouter App Rankings — 本周高增长产品",
            "",
            "| 产品 | Token/周 | WoW增长 | 品类 |",
            "|---|---|---|---|",
        ]
        for item in or_trending:
            m = item.get("metrics", {})
            cats = ", ".join(m.get("categories", []))
            wow = m.get("wow_pct", 0)
            lines.append(
                f"| [{item['title']}]({item['url']}) | {m.get('tokens_week', 'N/A')} | +{wow:.0f}% | {cats} |"
            )
        lines += ["", ""]

    # Section 2: Top Trending (cross-source)
    if top_trending:
        lines += [
            "## 🔥 跨源 Top 信号 (score ≥ 6 + trending)",
            "",
        ]
        for item in top_trending[:15]:
            emoji = SOURCE_EMOJI.get(item["source"], "•")
            score = item.get("score", 0)
            desc_zh = item.get("description_zh", "") or item.get("description_en", "")[:100]
            kw = ", ".join(item.get("keywords", [])[:4])
            lines += [
                f"### {emoji} {item['title']} `[{score}]`",
                f"**来源**: {item['source']} | **URL**: {item['url']}",
                f"{desc_zh}",
                f"**关键词**: {kw}" if kw else "",
                "",
            ]
        lines.append("")

    # Section 3: New Products
    if new_products:
        lines += [
            "## 🆕 新上线产品 (近30天首次出现)",
            "",
            "| 产品 | 来源 | Score | 描述 |",
            "|---|---|---|---|",
        ]
        for item in new_products:
            desc = (item.get("description_zh") or item.get("description_en", ""))[:80]
            lines.append(
                f"| [{item['title']}]({item['url']}) | {item['source']} | {item.get('score', 0)} | {desc} |"
            )
        lines += ["", ""]

    # Section 4: Per-source breakdown
    lines += ["## 📊 各源信号统计", ""]
    for source, src_items in sorted(by_source.items()):
        emoji = SOURCE_EMOJI.get(source, "•")
        avg_score = sum(i.get("score", 0) for i in src_items) / max(len(src_items), 1)
        trending_count = sum(1 for i in src_items if i.get("is_trending"))
        lines.append(f"- {emoji} **{source}**: {len(src_items)} 条, avg score {avg_score:.1f}, {trending_count} trending")
    lines += ["", ""]

    # Section 5: X/Twitter viral tweets
    x_items = sorted(
        [i for i in items if i["source"] == "x_twitter"],
        key=lambda x: x.get("metrics", {}).get("virality_score", 0),
        reverse=True
    )[:8]
    if x_items:
        lines += [
            "## 𝕏 X/Twitter — 高传播信号",
            "",
        ]
        for item in x_items:
            m = item.get("metrics", {})
            video_flag = " 🎬" if m.get("has_video") else ""
            lines += [
                f"- **@{m.get('username', '')}**{video_flag}: {item['title'][:100]}",
                f"  Likes: {m.get('likes', 0)} · RT: {m.get('retweets', 0)} · Bookmarks: {m.get('bookmarks', 0)} · Impressions: {m.get('impressions', 0):,}",
                f"  [{item['url']}]({item['url']})",
                "",
            ]

    report_md = "\n".join(lines)
    out_path = config.REPORTS_DIR / f"weekly_{date_str}.md"
    out_path.write_text(report_md, encoding="utf-8")
    log.info("Weekly brief written: %s", out_path)
    return out_path


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    p = generate_weekly_brief()
    print(f"Report: {p}")
