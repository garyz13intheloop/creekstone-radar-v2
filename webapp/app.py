"""
Creekstone Radar — Web UI v6
Premium dark intelligence terminal. Logo-first brand identity.
"""
import json
import sys
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

import config
from storage.store import load_from_cache
from models.item import SignalItem, FullProfile, TeamInfo, ScoreBreakdown
from enrichers.self_evolution import save_feedback
from reports.feishu_daily import sync_to_bitable

st.set_page_config(
    page_title="Creekstone Radar",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load logo
_LOGO_B64 = ""
try:
    _logo_path = Path(__file__).parent / "static" / "logo_crop.png"
    if _logo_path.exists():
        with open(_logo_path, "rb") as f:
            _LOGO_B64 = "data:image/png;base64," + base64.b64encode(f.read()).decode()
except Exception:
    pass

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,400&display=swap');

/* ── Reset ── */
*, *::before, *::after {{ box-sizing: border-box; }}
html, body, [class*="css"], .stApp, .stApp > div,
[data-testid="stAppViewContainer"], .main, .main > div, .block-container {{
    background-color: #080808 !important;
    color: #d4d4d4 !important;
    font-family: 'Inter', -apple-system, 'Helvetica Neue', sans-serif !important;
}}
.main .block-container {{ padding: 0 2.4rem 4rem !important; max-width: 1320px; }}
#MainMenu, footer, header {{ visibility: hidden; }}
::selection {{ background: rgba(201,168,76,.25); }}

/* ── Sidebar ── */
section[data-testid="stSidebar"] > div:first-child {{
    background-color: #0d0d0d !important;
    border-right: 1px solid #1e1e1e !important;
}}
section[data-testid="stSidebar"] * {{ color: #888 !important; }}
section[data-testid="stSidebar"] strong,
section[data-testid="stSidebar"] b {{ color: #c8c8c8 !important; }}

/* ── Global text ── */
p, span, div, li, td, th, label, h1, h2, h3, h4 {{ color: #d4d4d4 !important; }}
.stMarkdown p {{ color: #d4d4d4 !important; line-height: 1.7; }}
.stTextInput label p, .stTextArea label p,
.stSelectbox label p, .stSlider label p,
.stRadio label p, .stCheckbox label p {{
    color: #444 !important; font-size: 10.5px !important;
    text-transform: uppercase; letter-spacing: .06em;
}}

/* ── Sidebar logo area ── */
.sb-logo-wrap {{
    padding: 22px 20px 16px;
    border-bottom: 1px solid #1a1a1a;
    display: flex; align-items: center; gap: 12px;
}}
.sb-logo-img {{ width: 36px; height: 36px; object-fit: contain; }}
.sb-logo-text {{ display: flex; flex-direction: column; }}
.sb-brand {{ font-size: 13px; font-weight: 700; color: #C9A84C !important; letter-spacing: .12em; }}
.sb-sub {{ font-size: 10px; color: #3a3a3a !important; letter-spacing: .05em; margin-top: 2px; }}

/* ── Sidebar section ── */
.sb-sec {{ font-size: 9.5px; font-weight: 600; color: #333 !important; text-transform: uppercase; letter-spacing: .1em; padding: 14px 18px 5px; }}
.sb-stat-row {{ padding: 6px 18px 10px; display: flex; gap: 6px; }}
.sb-stat {{ flex: 1; background: #141414; border: 1px solid #1e1e1e; border-radius: 7px; padding: 8px 10px; text-align: center; }}
.sb-stat-n {{ font-size: 17px; font-weight: 800; color: #C9A84C !important; line-height: 1; }}
.sb-stat-l {{ font-size: 9px; color: #3a3a3a !important; margin-top: 3px; letter-spacing: .04em; }}

/* ── Card ── */
.rc {{
    background: #0f0f0f;
    border: 1px solid #1c1c1c;
    border-radius: 14px;
    padding: 20px 22px 16px;
    margin-bottom: 10px;
    transition: border-color .18s, background .18s;
    position: relative;
}}
.rc:hover {{ border-color: #2a2520; background: #111111; }}
.rc.hi {{
    border-color: rgba(201,168,76,.28);
    background: linear-gradient(135deg, rgba(201,168,76,.035) 0%, #0f0f0f 60%);
}}
.rc.hi::before {{
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(201,168,76,.4), transparent);
    border-radius: 14px 14px 0 0;
}}

/* ── Track pills ── */
.tb {{ display:inline-block; padding:2px 9px; border-radius:3px; font-size:10px; font-weight:600; letter-spacing:.04em; margin-right:5px; margin-bottom:4px; }}
.tb-A   {{ background:rgba(91,143,232,.12); color:#6b9de8; }}
.tb-B   {{ background:rgba(82,196,122,.1);  color:#5ecc82; }}
.tb-C   {{ background:rgba(201,168,76,.12); color:#C9A84C; }}
.tb-HW  {{ background:rgba(155,127,232,.1); color:#a48de8; }}
.tb-Te  {{ background:rgba(100,160,220,.08);color:#7ab4e8; }}
.tb-MM  {{ background:rgba(224,140,82,.1);  color:#e09c62; }}
.tb-LS  {{ background:rgba(224,82,82,.08);  color:#e07272; }}
.tb-sr  {{ background:rgba(255,255,255,.04);color:#555; }}

/* ── Score ── */
.sc-n {{ font-size:28px; font-weight:800; line-height:1; }}
.sc-d {{ font-size:11px; color:#333; font-weight:400; }}

/* ── Bars ── */
.bw {{ background:#181818; border-radius:3px; height:3px; }}
.bf {{ height:3px; border-radius:3px; }}

/* ── Card typography ── */
.ct {{ font-size:16.5px; font-weight:600; color:#e2e2e2 !important; margin:7px 0 3px; line-height:1.35; }}
.ct a {{ color:#e2e2e2 !important; text-decoration:none; }}
.ct a:hover {{ color:#C9A84C !important; }}
.mt {{ font-size:11px; color:#444 !important; margin-bottom:8px; line-height:1.6; }}
.ol {{ font-size:13.5px; color:#888 !important; line-height:1.65; margin:7px 0 0; }}
.sl {{ font-size:10px; font-weight:600; color:#3a3a3a !important; text-transform:uppercase; letter-spacing:.08em; margin:14px 0 5px; display:block; }}
.ib {{ background:rgba(201,168,76,.06); border-left:2px solid rgba(201,168,76,.5); border-radius:0 8px 8px 0; padding:10px 14px; font-size:13px !important; color:#b8a060 !important; line-height:1.65; margin:6px 0; }}
.bt {{ font-size:13px !important; color:#777 !important; line-height:1.68; }}
.nb {{ background:#141414; border:1px solid #1c1c1c; border-radius:8px; padding:10px 14px; font-size:13px !important; color:#666 !important; line-height:1.65; }}
.kw {{ display:inline-block; background:#141414; border:1px solid #1e1e1e; border-radius:4px; padding:2px 9px; font-size:11px !important; color:#555 !important; margin:2px 3px 2px 0; }}
.dl {{ border:none; border-top:1px solid #181818; margin:12px 0; }}

/* ── Topbar ── */
.topbar {{
    background: linear-gradient(180deg, #0d0d0d 0%, #080808 100%);
    border-bottom: 1px solid #1a1a1a;
    padding: 16px 28px 14px;
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 0;
}}
.tb-logo-wrap {{ display:flex; align-items:center; gap:14px; }}
.tb-logo {{ width:42px; height:42px; object-fit:contain; }}
.tb-brand {{ font-size:18px; font-weight:800; color:#e8e8e8 !important; letter-spacing:.01em; }}
.tb-sub {{ font-size:11px; color:#3a3a3a !important; margin-top:2px; letter-spacing:.03em; }}
.tb-badge {{
    font-size:9.5px; font-weight:700; color:#C9A84C;
    border:1px solid rgba(201,168,76,.3); border-radius:4px;
    padding:3px 9px; letter-spacing:.08em; text-transform:uppercase;
}}

/* ── Stats row ── */
.stats-row {{ display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin:16px 0; }}
.stat {{ background:#0f0f0f; border:1px solid #1c1c1c; border-radius:10px; padding:14px 16px; text-align:center; }}
.stat-n {{ font-size:22px; font-weight:800; color:#C9A84C !important; line-height:1; }}
.stat-l {{ font-size:9.5px; color:#3a3a3a !important; margin-top:4px; text-transform:uppercase; letter-spacing:.05em; }}

/* ── Section divider ── */
.sec-head {{
    display:flex; align-items:center; gap:10px;
    margin:20px 0 12px; padding-bottom:10px;
    border-bottom:1px solid #181818;
}}
.sec-head-line {{ flex:1; height:1px; background:#181818; }}
.sec-head-txt {{ font-size:10px; font-weight:600; color:#333; text-transform:uppercase; letter-spacing:.1em; }}

/* ── Inputs ── */
div.stTextInput > div > div > input,
div.stTextArea > div > div > textarea {{
    background:#141414 !important; border:1px solid #222 !important;
    border-radius:8px !important; color:#d4d4d4 !important; font-size:13px !important;
}}
div.stTextInput > div > div > input::placeholder,
div.stTextArea > div > div > textarea::placeholder {{ color:#333 !important; }}
div.stTextInput > div > div > input:focus,
div.stTextArea > div > div > textarea:focus {{
    border-color:rgba(201,168,76,.4) !important;
    box-shadow:0 0 0 2px rgba(201,168,76,.08) !important;
}}

/* ── Buttons ── */
div.stButton > button {{
    background:#141414 !important; border:1px solid #222 !important;
    border-radius:6px !important; color:#888 !important;
    font-size:12px !important; font-weight:500 !important; padding:5px 14px !important;
    transition:all .15s;
}}
div.stButton > button:hover {{
    background:#1a1a1a !important; border-color:#333 !important; color:#d4d4d4 !important;
}}
div.stButton > button[kind="primary"] {{
    background:rgba(201,168,76,.12) !important;
    border-color:rgba(201,168,76,.35) !important; color:#C9A84C !important;
}}
div.stButton > button[kind="primary"]:hover {{
    background:rgba(201,168,76,.2) !important;
}}

/* ── Expander ── */
[data-testid="stExpander"] {{
    border:1px solid #181818 !important; border-radius:9px !important;
    overflow:hidden; margin-top:10px;
}}
[data-testid="stExpander"] > details > summary {{
    background:#141414 !important; padding:9px 16px !important;
    cursor:pointer; list-style:none; font-size:0 !important;
}}
[data-testid="stExpander"] > details > summary::before {{
    content:'▸  展开详情';
    font-size:11px !important; font-weight:500;
    color:#444; font-family:inherit; letter-spacing:.02em;
}}
[data-testid="stExpander"] > details[open] > summary::before {{
    content:'▾  收起'; color:#666;
}}
[data-testid="stExpander"] > details > div {{
    background:#0f0f0f !important; padding:16px 18px !important;
}}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {{
    background:transparent !important; border-bottom:1px solid #1c1c1c !important; gap:0 !important;
}}
.stTabs [data-baseweb="tab"] {{
    background:transparent !important; color:#444 !important;
    font-size:12.5px !important; font-weight:500 !important;
    padding:9px 18px !important; border-bottom:2px solid transparent !important;
    transition:color .15s;
}}
.stTabs [aria-selected="true"] {{
    color:#C9A84C !important; border-bottom-color:#C9A84C !important;
    background:transparent !important;
}}
.stTabs [data-baseweb="tab-panel"] {{
    background:transparent !important; padding:16px 0 !important;
}}

/* ── Selectbox / Slider / Checkbox ── */
div.stSelectbox > div > div > div {{
    background:#141414 !important; border:1px solid #222 !important;
    color:#d4d4d4 !important; font-size:13px !important; border-radius:8px !important;
}}
[data-testid="stDivider"] {{ border-color:#1a1a1a !important; }}
div.stRadio label p {{ font-size:13px !important; color:#777 !important; }}
div.stRadio [aria-checked="true"] + div p {{ color:#C9A84C !important; }}
div.stCheckbox label p {{ color:#888 !important; font-size:13px !important; }}
div.stCheckbox label:has(input:checked) p {{ color:#c8c8c8 !important; }}
div.stSlider [data-testid="stThumbValue"] {{ color:#C9A84C !important; }}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width:3px; height:3px; }}
::-webkit-scrollbar-track {{ background:transparent; }}
::-webkit-scrollbar-thumb {{ background:#2a2a2a; border-radius:2px; }}
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
TRACK_CLS   = {"A":"tb-A","B":"tb-B","C":"tb-C","Hardware":"tb-HW","Tech":"tb-Te","Multimodal":"tb-MM","Lifestyle":"tb-LS","unknown":"tb-sr"}
TRACK_LBL   = {"A":"Track A · Framework","B":"Track B · FDE","C":"Track C · A2A","Hardware":"Hardware","Tech":"Tech / Research","Multimodal":"Multimodal","Lifestyle":"Lifestyle","unknown":"Unclassified"}
TRACK_COLOR = {"A":"#6b9de8","B":"#5ecc82","C":"#C9A84C","Hardware":"#a48de8","Tech":"#7ab4e8","Multimodal":"#e09c62","Lifestyle":"#e07272","unknown":"#444"}
TRACK_ORDER = ["A","B","C","Hardware","Multimodal","Tech","Lifestyle","unknown"]
SRC_LBL     = {"producthunt":"Product Hunt","github_trending":"GitHub Trending","github_events":"GitHub Events","arxiv":"arXiv","hackernews":"Hacker News","x_twitter":"X / Twitter","openrouter":"OpenRouter","huggingface":"HuggingFace"}

def score_color(s):
    if s >= 80: return "#5ecc82"
    if s >= 72: return "#C9A84C"
    if s >= 60: return "#6b9de8"
    return "#3a3a3a"

@st.cache_data(ttl=120)
def load_items(days):
    return load_from_cache(days=days)

def to_item(d):
    sb_r = d.get("score_breakdown") or {}
    sb = ScoreBreakdown(
        ai_native=sb_r.get("ai_native",0), niche=sb_r.get("niche",0),
        business=sb_r.get("business",0), team=sb_r.get("team",0),
        bonus=sb_r.get("bonus",0), penalty=sb_r.get("penalty",0),
        total=sb_r.get("total",0), reason=sb_r.get("reason",""),
        plus=sb_r.get("plus",[]), minus=sb_r.get("minus",[]),
    ) if sb_r else None
    fp_r = d.get("full_profile") or {}
    fp = FullProfile(
        one_liner=fp_r.get("one_liner",""), overview_zh=fp_r.get("overview_zh",""),
        biz_model_zh=fp_r.get("biz_model_zh",""), insight_zh=fp_r.get("insight_zh",""),
        score_narrative_zh=fp_r.get("score_narrative_zh",""),
        metrics_summary=fp_r.get("metrics_summary",""),
        founder_detail=fp_r.get("founder_detail",""),
        funding_rounds=fp_r.get("funding_rounds",""),
        links=fp_r.get("links",[]),
    ) if fp_r else None
    tm_r = d.get("team") or {}
    team = TeamInfo(
        founders=tm_r.get("founders",[]), funding_info=tm_r.get("funding_info",""),
        is_chinese_heritage=tm_r.get("is_chinese_heritage",False),
        notes=tm_r.get("notes",""),
    ) if tm_r else None
    return SignalItem(
        id=d.get("id",""), source=d.get("source",""), collected_at=d.get("collected_at",""),
        title=d.get("title",""), url=d.get("url",""),
        description_en=d.get("description_en",""), description_zh=d.get("description_zh",""),
        keywords=d.get("keywords",[]),
        track=d.get("track","unknown"), track_reason=d.get("track_reason",""),
        track_confidence=d.get("track_confidence","low"),
        fde_index=d.get("fde_index",0),
        score=float(d.get("score",0)),
        score_breakdown=sb, team=team, full_profile=fp,
        is_trending=d.get("is_trending",False), is_new=d.get("is_new",False),
        feedback_state=d.get("feedback_state","pending"),
        feedback_note=d.get("feedback_note",""),
        metrics=d.get("metrics",{}),
    )

def enrich_founder(item):
    import requests as rq
    if not config.LLM_API_KEY: return "LLM key 未配置"
    try:
        r = rq.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            headers={"Authorization":f"Bearer {config.LLM_API_KEY}","Content-Type":"application/json"},
            json={"model":config.S3_MODEL,"messages":[{"role":"user","content":
                f"调研以下AI产品的创始人背景（中文，专有名词英文）：\n产品：{item.title}\n网址：{item.url}\n描述：{item.description_en[:400]}\n\n包含：姓名、教育背景、过往经历、是否华人、融资情况。"}],
                "temperature":0.3,"max_tokens":500},
            timeout=60,
        )
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"调研失败：{e}"

def render_card(item, idx):
    track = item.track or "unknown"
    tc    = TRACK_CLS.get(track,"tb-sr")
    tl    = TRACK_LBL.get(track, track)
    sl    = SRC_LBL.get(item.source, item.source)
    fp    = item.full_profile
    sb    = item.score_breakdown
    m     = item.metrics
    score = item.score
    hi    = score >= 75

    st.markdown(f'<div class="rc{"  hi" if hi else ""}">', unsafe_allow_html=True)

    col_main, col_sc = st.columns([9, 1])
    with col_main:
        badges = f'<span class="tb {tc}">{tl}</span><span class="tb tb-sr">{sl}</span>'
        if item.is_trending: badges += '<span class="tb" style="background:rgba(201,168,76,.09);color:#9a7a30;">trending</span>'
        if item.is_new: badges += '<span class="tb" style="background:rgba(82,196,122,.07);color:#4a9c60;">new</span>'
        if item.track == "B" and item.fde_index: badges += f'<span class="tb" style="background:rgba(82,196,122,.07);color:#4a9c60;">FDE {item.fde_index}/10</span>'
        st.markdown(badges, unsafe_allow_html=True)
        st.markdown(
            f'<div class="ct"><a href="{item.url}" target="_blank">{item.title}</a></div>',
            unsafe_allow_html=True,
        )
        meta_parts = []
        if item.collected_at: meta_parts.append(item.collected_at[:10])
        src = item.source
        if src=="producthunt" and m.get("votes"):    meta_parts.append(f"PH ▲{m['votes']}")
        elif src in ("github_trending","github_events"):
            if m.get("stars"): meta_parts.append(f"★ {m['stars']:,}")
            spd = m.get("stars_today") or m.get("stars_per_day",0)
            if spd: meta_parts.append(f"+{spd:.0f}/day")
        elif src=="openrouter" and m.get("wow_pct"): meta_parts.append(f"OR +{m['wow_pct']:.0f}% WoW")
        elif src=="hackernews" and m.get("points"):  meta_parts.append(f"HN {m['points']}pts")
        elif src=="x_twitter":                       meta_parts.append(f"♥{m.get('likes',0)}  ⊃{m.get('bookmarks',0)}")
        if item.track_reason: meta_parts.append(item.track_reason)
        st.markdown(f'<div class="mt">{" · ".join(meta_parts)}</div>', unsafe_allow_html=True)

    with col_sc:
        if score > 0:
            c = score_color(score)
            st.markdown(
                f'<div style="text-align:right;padding-top:8px;">'
                f'<span class="sc-n" style="color:{c};">{score:.0f}</span>'
                f'<span class="sc-d"> /100</span></div>',
                unsafe_allow_html=True,
            )

    ol = (fp.one_liner if fp and fp.one_liner else "") or item.description_zh or item.description_en[:120]
    if ol:
        st.markdown(f'<div class="ol">{ol}</div>', unsafe_allow_html=True)

    with st.expander("", expanded=False):
        if sb and sb.total > 0:
            st.markdown('<span class="sl">评分明细</span>', unsafe_allow_html=True)
            for lbl, val, mx, clr in [
                ("AI Native", sb.ai_native, 30, "#6b9de8"),
                ("Niche 壁垒", sb.niche, 25, "#5ecc82"),
                ("商业模式",   sb.business, 20, "#C9A84C"),
                ("团队",       sb.team, 15, "#a48de8"),
                ("加减分",     sb.bonus - sb.penalty, 10, "#e09c62"),
            ]:
                pct = max(0, int(val/mx*100)) if mx else 0
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:10px;margin:5px 0;">'
                    f'<span style="font-size:11px;color:#444;width:64px;flex-shrink:0;">{lbl}</span>'
                    f'<div class="bw" style="flex:1;"><div class="bf" style="width:{pct}%;background:{clr};"></div></div>'
                    f'<span style="font-size:12px;font-weight:600;color:#777;width:38px;text-align:right;">{val}/{mx}</span></div>',
                    unsafe_allow_html=True,
                )
            if sb.plus:
                st.markdown(f'<div class="bt" style="color:#4a9c60 !important;margin-top:6px;">+ {" · ".join(sb.plus)}</div>', unsafe_allow_html=True)
            if sb.minus:
                st.markdown(f'<div class="bt" style="color:#c05050 !important;">− {" · ".join(sb.minus)}</div>', unsafe_allow_html=True)
            if sb.reason:
                st.markdown(f'<div class="nb" style="margin-top:8px;">{sb.reason}</div>', unsafe_allow_html=True)

        st.markdown('<div class="dl"></div>', unsafe_allow_html=True)

        if fp:
            if fp.overview_zh:
                st.markdown('<span class="sl">产品介绍</span>', unsafe_allow_html=True)
                st.markdown(f'<div class="bt">{fp.overview_zh}</div>', unsafe_allow_html=True)
            if fp.biz_model_zh:
                st.markdown('<span class="sl">商业模式</span>', unsafe_allow_html=True)
                st.markdown(f'<div class="bt">{fp.biz_model_zh}</div>', unsafe_allow_html=True)
            if fp.insight_zh:
                st.markdown('<span class="sl">Creekstone 视角</span>', unsafe_allow_html=True)
                st.markdown(f'<div class="ib">{fp.insight_zh}</div>', unsafe_allow_html=True)
            if fp.score_narrative_zh:
                st.markdown('<span class="sl">评分解读</span>', unsafe_allow_html=True)
                st.markdown(f'<div class="bt">{fp.score_narrative_zh}</div>', unsafe_allow_html=True)
            if fp.metrics_summary:
                st.markdown('<span class="sl">数据指标</span>', unsafe_allow_html=True)
                st.markdown(f'<div class="bt">{fp.metrics_summary}</div>', unsafe_allow_html=True)
            if fp.founder_detail:
                st.markdown('<span class="sl">Founder 背景</span>', unsafe_allow_html=True)
                st.markdown(f'<div class="bt">{fp.founder_detail}</div>', unsafe_allow_html=True)

        team = item.team
        if team and (team.founders or team.funding_info or team.notes):
            st.markdown('<span class="sl">团队 & 融资</span>', unsafe_allow_html=True)
            if team.founders:
                st.markdown(f'<div class="bt"><span style="color:#3a3a3a;">创始人：</span>{" / ".join(team.founders)}</div>', unsafe_allow_html=True)
            if team.funding_info:
                st.markdown(f'<div class="bt"><span style="color:#3a3a3a;">融资：</span>{team.funding_info}</div>', unsafe_allow_html=True)
            if team.is_chinese_heritage:
                st.markdown('<div class="bt" style="color:#C9A84C !important;">◈ 华人创始人</div>', unsafe_allow_html=True)
            if team.notes:
                st.markdown(f'<div class="bt">{team.notes}</div>', unsafe_allow_html=True)

        if item.keywords:
            st.markdown("".join(f'<span class="kw">{k}</span>' for k in item.keywords), unsafe_allow_html=True)

        st.markdown('<div class="dl"></div>', unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns([1,1,1,2])
        with c1:
            if st.button("跟进", key=f"fu_{item.id}_{idx}", type="primary"):
                save_feedback(item.id, item.title, "follow_up", item.score, item.track, "")
                with st.spinner("同步中…"):
                    ok = sync_to_bitable(item)
                st.success("已同步" if ok else "已记录（Bitable 未配置）")
        with c2:
            if st.button("忽略", key=f"ig_{item.id}_{idx}"):
                save_feedback(item.id, item.title, "ignored", item.score, item.track, "")
                st.toast("已忽略")
        with c3:
            if st.button("Watchlist", key=f"wl_{item.id}_{idx}"):
                save_feedback(item.id, item.title, "watchlist", item.score, item.track, "")
                st.toast("已加入")
        with c4:
            if st.button("◎ 扒 Founder", key=f"fd_{item.id}_{idx}"):
                with st.spinner("调研中…"):
                    res = enrich_founder(item)
                st.markdown(f'<div class="nb" style="margin-top:6px;">{res}</div>', unsafe_allow_html=True)



    st.markdown('</div>', unsafe_allow_html=True)


def main():
    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        logo_html = f'<img src="{_LOGO_B64}" class="sb-logo-img">' if _LOGO_B64 else '<div style="width:36px;height:36px;background:rgba(201,168,76,.15);border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:16px;color:#C9A84C;">◈</div>'
        st.markdown(
            f'<div class="sb-logo-wrap">'
            f'{logo_html}'
            f'<div class="sb-logo-text"><div class="sb-brand">CREEKSTONE</div><div class="sb-sub">Radar · Intelligence</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)
        st.markdown('<div class="sb-sec">查看最近</div>', unsafe_allow_html=True)
        days_back = st.slider("查看最近", 1, 120, 30, format="%d 天", label_visibility="collapsed")
        raw_items = load_items(days=days_back)
        items = [to_item(d) for d in raw_items]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_n = sum(1 for i in items if i.collected_at[:10] == today)
        high_n  = sum(1 for i in items if i.score >= 75)

        st.markdown(
            f'<div class="sb-stat-row">'
            f'<div class="sb-stat"><div class="sb-stat-n">{len(items)}</div><div class="sb-stat-l">总信号</div></div>'
            f'<div class="sb-stat"><div class="sb-stat-n">{today_n}</div><div class="sb-stat-l">今日</div></div>'
            f'<div class="sb-stat"><div class="sb-stat-n">{high_n}</div><div class="sb-stat-l">高分</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.divider()
        st.markdown('<div class="sb-sec">Track 筛选</div>', unsafe_allow_html=True)
        all_tracks = [t for t in TRACK_ORDER if any(i.track == t for i in items)]
        sel_tracks = []
        for t in all_tracks:
            cnt = sum(1 for i in items if i.track == t)
            dot_c = TRACK_COLOR.get(t, "#444")
            if st.checkbox(f"{TRACK_LBL.get(t,t)}  ({cnt})", value=True, key=f"ck_{t}"):
                sel_tracks.append(t)

        st.divider()
        st.markdown('<div class="sb-sec">来源</div>', unsafe_allow_html=True)
        all_sources = sorted(set(i.source for i in items))
        sel_sources = []
        for src in all_sources:
            cnt = sum(1 for i in items if i.source == src)
            if st.checkbox(f"{SRC_LBL.get(src,src)}  ({cnt})", value=True, key=f"ck_src_{src}"):
                sel_sources.append(src)

        st.divider()
        st.markdown('<div class="sb-sec">最低评分</div>', unsafe_allow_html=True)
        min_score = st.slider("最低评分", 0, 100, 0, label_visibility="collapsed")
        all_dates = sorted(set(i.collected_at[:10] for i in items if i.collected_at), reverse=True)
        st.markdown('<div class="sb-sec">日期</div>', unsafe_allow_html=True)
        sel_date  = st.selectbox("日期", ["全部"] + all_dates, label_visibility="collapsed")
        st.markdown('<div class="sb-sec">排序</div>', unsafe_allow_html=True)
        sort_by   = st.selectbox("排序", ["评分高→低", "日期新→旧", "来源"], label_visibility="collapsed")

    # ── Topbar ────────────────────────────────────────────────────────────────
    logo_tb = f'<img src="{_LOGO_B64}" class="tb-logo">' if _LOGO_B64 else '<div style="width:42px;height:42px;background:rgba(201,168,76,.12);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:20px;color:#C9A84C;">◈</div>'
    st.markdown(
        f'<div class="topbar">'
        f'<div class="tb-logo-wrap">'
        f'{logo_tb}'
        f'<div><div class="tb-brand">Creekstone Radar</div>'
        f'<div class="tb-sub">AI Sourcing Intelligence · Daily Feed</div></div>'
        f'</div>'
        f'<div class="tb-badge">Intelligence Platform</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Search ────────────────────────────────────────────────────────────────
    st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)
    search = st.text_input("", placeholder="🔍  搜索产品名称、描述、关键词…", label_visibility="collapsed")

    # ── Stats ─────────────────────────────────────────────────────────────────
    scored = [i for i in items if i.score > 0]
    avg_sc = sum(i.score for i in scored)/len(scored) if scored else 0
    track_n = len(set(i.track for i in items if i.track != "unknown"))

    st.markdown(
        f'<div class="stats-row">'
        f'<div class="stat"><div class="stat-n">{len(items)}</div><div class="stat-l">总信号数</div></div>'
        f'<div class="stat"><div class="stat-n">{today_n}</div><div class="stat-l">今日新增</div></div>'
        f'<div class="stat"><div class="stat-n">{avg_sc:.0f}</div><div class="stat-l">平均评分</div></div>'
        f'<div class="stat"><div class="stat-n">{high_n}</div><div class="stat-l">高分 ≥75</div></div>'
        f'<div class="stat"><div class="stat-n">{days_back}</div><div class="stat-l">覆盖天数</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Filter ────────────────────────────────────────────────────────────────
    filtered = items
    if sel_tracks:  filtered = [i for i in filtered if i.track in sel_tracks]
    if sel_sources: filtered = [i for i in filtered if i.source in sel_sources]
    if min_score:   filtered = [i for i in filtered if i.score >= min_score]
    if sel_date != "全部": filtered = [i for i in filtered if i.collected_at[:10] == sel_date]
    if search.strip():
        q = search.lower().replace("🔍","").strip()
        filtered = [i for i in filtered if
            q in i.title.lower() or q in (i.description_zh or "").lower()
            or q in (i.description_en or "").lower()
            or any(q in k.lower() for k in i.keywords)
            or (i.full_profile and (q in (i.full_profile.one_liner or "").lower()
                or q in (i.full_profile.overview_zh or "").lower()))]

    if sort_by == "评分高→低":   filtered.sort(key=lambda x: x.score, reverse=True)
    elif sort_by == "日期新→旧": filtered.sort(key=lambda x: x.collected_at, reverse=True)
    else:                        filtered.sort(key=lambda x: x.source)

    # ── View toggle ───────────────────────────────────────────────────────────
    cv1, cv2 = st.columns([4, 6])
    with cv1:
        st.markdown(
            f'<div style="font-size:11px;color:#3a3a3a;padding:6px 0;">'
            f'显示 <span style="color:#C9A84C;font-weight:600;">{len(filtered)}</span> / {len(items)} 条</div>',
            unsafe_allow_html=True,
        )
    with cv2:
        view = st.radio("", ["按 Track 分组", "综合列表"], horizontal=True, label_visibility="collapsed")

    # ── Render ────────────────────────────────────────────────────────────────
    if view == "按 Track 分组":
        active = [t for t in TRACK_ORDER if any(i.track == t for i in filtered)]
        if not active:
            st.markdown('<div class="bt" style="padding:24px 0;color:#3a3a3a !important;">没有符合条件的数据</div>', unsafe_allow_html=True)
            return
        tab_labels = [f"{TRACK_LBL.get(t,t)}  ({sum(1 for i in filtered if i.track==t)})" for t in active]
        tabs = st.tabs(tab_labels)
        for tab, track in zip(tabs, active):
            with tab:
                for idx, item in enumerate([i for i in filtered if i.track == track]):
                    render_card(item, idx)
    else:
        if not filtered:
            st.markdown('<div class="bt" style="padding:24px 0;color:#3a3a3a !important;">没有符合条件的数据</div>', unsafe_allow_html=True)
        for idx, item in enumerate(filtered):
            render_card(item, idx)


if __name__ == "__main__":
    main()
