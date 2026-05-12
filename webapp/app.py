"""
Creekstone Radar v2 — Streamlit Dashboard
Full project cards with team info, Similarweb traffic, scoring breakdown,
Track classification, FDE index, and Gary's Watchlist management.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

import config
from storage.store import load_recent_daily
from collectors.similarweb_monitor import get_traffic_for_domain
from models.item import extract_domain
from enrichers.self_evolution import save_feedback, load_few_shots

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Creekstone Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

TRACK_COLOR = {"A": "#2563EB", "B": "#16A34A", "C": "#D97706", "unknown": "#9CA3AF"}
TRACK_LABEL = {"A": "Track A — 框架", "B": "Track B — 垂直FDE", "C": "Track C — A2A", "unknown": "未分类"}
SOURCE_EMOJI = {
    "producthunt": "🚀", "github_trending": "⭐", "github_events": "📈",
    "arxiv": "📄", "hackernews": "🟠", "discord": "💬", "reddit": "🔴",
    "x_twitter": "𝕏", "openrouter": "🤖", "huggingface": "🤗",
}

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_items(days: int = 7) -> list[dict]:
    return load_recent_daily(days=days)

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 Creekstone Radar")
    st.markdown("---")

    days_back = st.slider("查看最近 N 天", 1, 30, 7)
    items = load_items(days=days_back)

    st.markdown(f"**共 {len(items)} 条信号**")
    st.markdown("---")

    # Track filter
    st.markdown("**Track 筛选**")
    show_A = st.checkbox("🔵 Track A — 框架", value=True)
    show_B = st.checkbox("🟢 Track B — 垂直FDE", value=True)
    show_C = st.checkbox("🟡 Track C — A2A", value=True)
    show_unknown = st.checkbox("⚪ 未分类", value=False)

    track_filter = set()
    if show_A: track_filter.add("A")
    if show_B: track_filter.add("B")
    if show_C: track_filter.add("C")
    if show_unknown: track_filter.add("unknown")

    # Source filter
    st.markdown("**来源筛选**")
    all_sources = sorted(set(i.get("source", "") for i in items))
    selected_sources = st.multiselect(
        "信号来源",
        options=all_sources,
        default=all_sources,
        format_func=lambda x: f"{SOURCE_EMOJI.get(x, '•')} {x}"
    )

    # Score filter
    st.markdown("**评分筛选**")
    min_score = st.slider("最低 score", 0, 100, 50)
    fde_only = st.checkbox("仅看 FDE ≥ 7（Track B）", value=False)

    # Special filters
    st.markdown("**特殊筛选**")
    watchlist_only = st.checkbox("仅看 Watchlist", value=False)
    trending_only = st.checkbox("仅看 Trending", value=False)
    traffic_only = st.checkbox("有 Similarweb 数据", value=False)

    st.markdown("---")
    sort_by = st.selectbox("排序方式", ["score 降序", "日期降序", "FDE 降序", "WoW增长 降序"])

# ── Apply filters ─────────────────────────────────────────────────────────────
def apply_filters(items: list[dict]) -> list[dict]:
    filtered = items
    if track_filter:
        filtered = [i for i in filtered if i.get("track", "unknown") in track_filter]
    if selected_sources:
        filtered = [i for i in filtered if i.get("source", "") in selected_sources]
    filtered = [i for i in filtered if float(i.get("score", 0)) >= min_score]
    if fde_only:
        filtered = [i for i in filtered if i.get("fde_index", 0) >= 7]
    if watchlist_only:
        filtered = [i for i in filtered if i.get("feedback_state") == "watchlist"]
    if trending_only:
        filtered = [i for i in filtered if i.get("is_trending") or i.get("is_spike")]
    if traffic_only:
        filtered = [i for i in filtered if get_traffic_for_domain(extract_domain(i.get("url", "")))]
    return filtered

def sort_items(items: list[dict]) -> list[dict]:
    if sort_by == "score 降序":
        return sorted(items, key=lambda x: float(x.get("score", 0)), reverse=True)
    if sort_by == "日期降序":
        return sorted(items, key=lambda x: x.get("collected_at", ""), reverse=True)
    if sort_by == "FDE 降序":
        return sorted(items, key=lambda x: int(x.get("fde_index", 0)), reverse=True)
    if sort_by == "WoW增长 降序":
        return sorted(items, key=lambda x: float(x.get("wow_growth_pct") or x.get("metrics", {}).get("wow_pct", 0)), reverse=True)
    return items

display_items = sort_items(apply_filters(items))

# ── Header stats ──────────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("总信号", len(display_items))
col2.metric("Track A", sum(1 for i in display_items if i.get("track") == "A"))
col3.metric("Track B", sum(1 for i in display_items if i.get("track") == "B"))
col4.metric("Track C", sum(1 for i in display_items if i.get("track") == "C"))
col5.metric("Trending", sum(1 for i in display_items if i.get("is_trending") or i.get("is_spike")))

st.markdown("---")

# ── Project cards ─────────────────────────────────────────────────────────────
if not display_items:
    st.info("没有符合条件的信号，请调整筛选条件。")

for item in display_items[:100]:   # cap at 100 for performance
    track = item.get("track", "unknown")
    score = float(item.get("score", 0))
    fde_idx = int(item.get("fde_index", 0))
    source = item.get("source", "")
    title = item.get("title", "(无标题)")
    url = item.get("url", "#")
    desc_zh = item.get("description_zh", "") or item.get("description_en", "")[:200]
    keywords = item.get("keywords", [])
    metrics = item.get("metrics", {})
    breakdown = item.get("score_breakdown") or {}
    track_reason = item.get("track_reason", "")
    feedback_state = item.get("feedback_state", "pending")
    is_trending = item.get("is_trending") or item.get("is_spike")
    collected_at = item.get("collected_at", "")[:10]

    # Card border color by track
    border_color = TRACK_COLOR.get(track, "#9CA3AF")
    trending_badge = "🔥 " if is_trending else ""

    with st.container():
        # Card header
        header_cols = st.columns([0.6, 0.15, 0.12, 0.13])
        with header_cols[0]:
            st.markdown(
                f"**{trending_badge}[{title}]({url})**  "
                f"`{SOURCE_EMOJI.get(source,'•')} {source}`  "
                f"<span style='color:{border_color};font-size:12px'>{TRACK_LABEL.get(track,'')}</span>",
                unsafe_allow_html=True
            )
        with header_cols[1]:
            score_color = "#16A34A" if score >= 70 else "#D97706" if score >= 50 else "#DC2626"
            st.markdown(f"<span style='font-size:20px;font-weight:600;color:{score_color}'>{score:.0f}</span> <span style='color:#9CA3AF;font-size:12px'>/100</span>", unsafe_allow_html=True)
        with header_cols[2]:
            if track == "B" and fde_idx > 0:
                fde_color = "#16A34A" if fde_idx >= 7 else "#D97706"
                st.markdown(f"<span style='color:{fde_color};font-size:13px'>FDE: **{fde_idx}**/10</span>", unsafe_allow_html=True)
        with header_cols[3]:
            fb_state_display = {"interested": "❤️ 感兴趣", "watchlist": "📌 Watchlist", "ignored": "🚫 已忽略", "pending": ""}.get(feedback_state, "")
            if fb_state_display:
                st.markdown(f"<span style='font-size:12px;color:#6B7280'>{fb_state_display}</span>", unsafe_allow_html=True)

        # Main content
        tab_overview, tab_score, tab_team, tab_traffic = st.tabs(["概览", "评分详情", "团队信息", "流量数据"])

        with tab_overview:
            col_desc, col_metrics = st.columns([0.6, 0.4])
            with col_desc:
                if desc_zh:
                    st.markdown(f"*{desc_zh[:300]}*")
                if keywords:
                    st.markdown(" ".join([f"`{kw}`" for kw in keywords[:6]]))
                if track_reason:
                    st.caption(f"Track分类原因：{track_reason}")
                st.caption(f"采集时间：{collected_at} | 来源：{source}")

            with col_metrics:
                # Source-specific metrics
                if source == "producthunt":
                    st.metric("PH Votes", metrics.get("votes", 0))
                elif source in ("github_trending", "github_events"):
                    c1, c2 = st.columns(2)
                    c1.metric("Stars", f"{metrics.get('stars', 0):,}")
                    c2.metric("今日新增", f"+{metrics.get('stars_today', metrics.get('stars_per_day', 0))}")
                elif source == "openrouter":
                    c1, c2 = st.columns(2)
                    c1.metric("Token/周", metrics.get("tokens_week", ""))
                    c2.metric("WoW增长", f"+{metrics.get('wow_pct', 0):.0f}%")
                elif source == "x_twitter":
                    c1, c2 = st.columns(2)
                    c1.metric("Likes", metrics.get("likes", 0))
                    c2.metric("Bookmarks", metrics.get("bookmarks", 0))
                elif source == "hackernews":
                    c1, c2 = st.columns(2)
                    c1.metric("HN Points", metrics.get("points", 0))
                    c2.metric("Comments", metrics.get("comments", 0))
                elif source == "reddit":
                    c1, c2 = st.columns(2)
                    c1.metric("Upvotes", metrics.get("upvotes", 0))
                    c2.metric("r/", metrics.get("subreddit", ""))

            # Feedback buttons
            fb_cols = st.columns([0.15, 0.15, 0.15, 0.55])
            item_id = item.get("id", "")
            with fb_cols[0]:
                if st.button("❤️ 感兴趣", key=f"int_{item_id}"):
                    save_feedback(item_id, title, "interested", track=track)
                    st.rerun()
            with fb_cols[1]:
                if st.button("📌 Watchlist", key=f"wl_{item_id}"):
                    save_feedback(item_id, title, "watchlist", track=track)
                    st.rerun()
            with fb_cols[2]:
                if st.button("🚫 忽略", key=f"ign_{item_id}"):
                    save_feedback(item_id, title, "ignored", track=track)
                    st.rerun()

        with tab_score:
            if breakdown:
                dims = [
                    ("AI Native", breakdown.get("ai_native", 0), 30),
                    ("Niche 壁垒", breakdown.get("niche", 0), 25),
                    ("商业模式", breakdown.get("business", 0), 20),
                    ("团队进化力", breakdown.get("team", 0), 15),
                ]
                for dim_name, dim_val, dim_max in dims:
                    pct = dim_val / dim_max if dim_max > 0 else 0
                    st.markdown(
                        f"**{dim_name}** {dim_val}/{dim_max}  "
                        f"{'█' * int(pct * 20)}{'░' * (20 - int(pct * 20))}"
                    )
                bonus = breakdown.get("bonus", 0)
                penalty = breakdown.get("penalty", 0)
                if bonus: st.success(f"加分项: +{bonus}")
                if penalty: st.error(f"减分项: -{penalty}")
                reason = breakdown.get("reason", "")
                if reason:
                    st.info(f"评分理由：{reason}")
                plus_pts = breakdown.get("plus", [])
                minus_pts = breakdown.get("minus", [])
                if plus_pts:
                    st.markdown("**加分点：** " + " · ".join(plus_pts))
                if minus_pts:
                    st.markdown("**减分点：** " + " · ".join(minus_pts))

                # Score override
                with st.expander("✏️ 覆盖评分（Gary修正）"):
                    new_score = st.number_input("新评分", 0, 100, int(score), key=f"ns_{item_id}")
                    new_reason = st.text_input("修正原因", key=f"nr_{item_id}")
                    if st.button("保存覆盖", key=f"sv_{item_id}"):
                        save_feedback(item_id, title, "interested", track=track,
                                     score_override=new_score, score_reason=new_reason)
                        st.success("已保存")
            else:
                st.info("暂无评分详情（未运行 S3 评分）")

        with tab_team:
            team = item.get("team")
            if team:
                if team.get("founders"):
                    st.markdown("**创始人：** " + " / ".join(team["founders"]))
                if team.get("founded_year"):
                    st.markdown(f"**成立年份：** {team['founded_year']}")
                if team.get("location"):
                    st.markdown(f"**地点：** {team['location']}")
                if team.get("is_chinese_heritage"):
                    st.success("🇨🇳 有华人创始人背景")
                if team.get("notes"):
                    st.markdown(f"*{team['notes']}*")
            else:
                st.info("团队信息待抓取（enricher 尚未运行）")
                if st.button("🔍 立即抓取团队信息", key=f"team_{item_id}"):
                    st.info(f"将在下次 enricher 运行时处理：{url}")

        with tab_traffic:
            domain = extract_domain(url)
            traffic = get_traffic_for_domain(domain) if domain else None
            if traffic:
                c1, c2, c3 = st.columns(3)
                visits = traffic.get("total_visits", 0)
                c1.metric("月访问量", f"{visits/1e6:.1f}M" if visits > 1e6 else f"{visits/1e3:.0f}K")
                mom = traffic.get("mom_growth_pct", 0)
                c2.metric("月环比增长", f"+{mom*100:.1f}%" if mom > 0 else f"{mom*100:.1f}%",
                          delta=f"+{mom*100:.1f}%" if mom > 0.4 else None)
                c3.metric("快照月份", traffic.get("snapshot_date", ""))
                if traffic.get("top_country"):
                    st.caption(f"主要流量来源：{traffic['top_country']}")
                if traffic.get("is_spike"):
                    st.warning(f"⚡ 流量 spike 检测：MoM +{mom*100:.1f}%（超过40%阈值）")
            else:
                st.info(f"暂无 Similarweb 数据  ·  域名：`{domain}`")
                st.caption("每周一运行流量快照，或手动将域名加入 watchlist.json")

        st.markdown("---")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(
    f"<div style='text-align:center;color:#9CA3AF;font-size:12px'>"
    f"Creekstone Radar v2 · {len(items)} signals · "
    f"最后更新 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    f"</div>",
    unsafe_allow_html=True
)
