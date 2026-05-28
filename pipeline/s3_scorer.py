"""
S3 — Track-aware full scoring + rich profile generation.
v3: expanded to 7 Tracks, generates FullProfile for items >= ENRICH_THRESHOLD,
    improved retry logic (3 attempts + exponential backoff), increased timeout.
"""
from __future__ import annotations
import json
import logging
import os
import re
import time
from typing import Any

import requests

import config
from models.item import SignalItem, ScoreBreakdown, FullProfile

log = logging.getLogger(__name__)

# Items with score >= this threshold get web-search enrichment + full profile
ENRICH_THRESHOLD: int = int(os.getenv("ENRICH_SCORE_THRESHOLD", "72"))

# ── Track benchmarks ──────────────────────────────────────────────────────────
TRACK_BENCHMARKS = {
    "A": """Track A 基准参照（Agent框架 & 通用效率工具）：
- LangChain score≈72：生态最大但商业化弱，被大量产品依赖
- OpenHands score≈78：开源coding agent，工具调用强，开发者社区活跃
- Exa score≈74：搜索API专为Agent设计，模型无关，采用率快速增长
- Cursor SDK score≈82：IDE级agent框架，开发者留存极高
- Dify score≈76：低代码Agent构建平台，中国团队，快速全球化""",

    "B": """Track B 基准参照（垂直FDE）：
- Harvey($8B) score≈91：法律FDE，私有判例数据，律师停用即瘫痪，FDE指数9
- Abridge($5.3B) score≈88：医疗文档FDE，源头劫持医患对话，FDE指数8
- Sierra($10B) score≈90：B2B客服FDE，深度绑定企业知识库，FDE指数9
- EvenUp($2B) score≈83：法律理赔FDE，获赔金额提高30%+，FDE指数7
评分关键：同等其他条件下，FDE指数高的项目score应比FDE指数低的高5-8分""",

    "C": """Track C 基准参照（A2A网络，纯软件协议层）：
- HeyAgent score≈74：A2A协议早期探索，已有8个agent接入，网络效应初现
- AgentOps score≈70：agent运维监控，被多个agent采用，更像基础设施""",

    "Hardware": """Track Hardware 基准参照（硬件层）：
- Figure AI score≈85：具身智能，BMW工厂部署，硬件+软件飞轮
- 1X score≈80：人形机器人，OpenAI投资，家庭场景
- Groq score≈78：推理芯片，Token速度领先，面向API开发者
硬件+AI整合度是关键评分因素：纯硬件无AI score上限≈65""",

    "Tech": """Track Tech 基准参照（技术突破 & 学术）：
- Flash Attention paper score≈88：改变Transformer训练效率的基础算法
- LoRA paper score≈85：让微调普惠化的关键技术
- Mamba score≈80：挑战Transformer架构的新范式
评分重点：技术贡献的根本性 / 是否会推动下游产品革命 / 复现难度""",

    "Multimodal": """Track Multimodal 基准参照（多模态应用）：
- ElevenLabs score≈86：语音合成，情感表达领先，API生态强
- HeyGen score≈84：视频数字人，企业营销场景，华人团队
- Runway score≈82：视频生成，创意内容，好莱坞合作
- Kling score≈80：视频生成，快手出品，中文内容领先
多模态质量 + 商业闭环是核心评分维度""",

    "Lifestyle": """Track Lifestyle 基准参照（情感陪伴 & 生活类）：
- Character.AI score≈78：情感陪伴，用户粘性极高，变现待解
- Pi score≈72：个人AI，情感支持，月活稳定
- Replika score≈68：情感陪伴，付费率高但增长放缓
评分重点：用户留存 / 付费意愿 / 监管风险 / 是否有真实刚需""",
}

# ── FDE section (Track B only) ────────────────────────────────────────────────
FDE_SECTION = """【FDE指数（Track B专用，0-10）】
- 0-3: 单点工具，未形成专家级覆盖
- 4-6: 某子场景深度，数据积累中
- 7-8: 覆盖>60%高频任务，有私有数据飞轮
- 9-10: FDE达成，停用即严重影响业务
fde_index每+1约对应Niche维度+2分"""

# ── Master system prompt ──────────────────────────────────────────────────────
BASE_SYSTEM_PROMPT = """你是 Creekstone Ventures 的投资评审助手。
输出严格JSON，内容全中文，项目名称和专有名词保留英文。

【当前产品Track: {track_label}】
{track_benchmark}

【评分标尺——满分100分，必须差异化！】

① AI Native程度（0-30分）
  28-30：用户行为即训练数据，真正自进化闭环，已从对话走向确定性工作流
  22-27：明显AI-native设计，工具调用/内存/规划已上线，有数据飞轮雏形
  15-21：传统软件加了AI功能，核心流程未因AI重构
  0-14 ：套壳或AI仅作装饰，无实质agent能力

② 技术壁垒 & Niche（0-25分）
  22-25：私有数据飞轮已形成，几乎无人愿做的冷门方向，壁垒极高
  17-21：有场景护城河，技术路径有一定非共识性
  11-16：场景清晰但可替代性高，壁垒较弱
  0-10 ：通用工具，同质化严重；或信息不足无法判断(-3惩罚)

③ 商业模式 & Exit（0-20分）
  18-20：结果付费/成功分成，明确收购路径，服务不可替代的高价值用户
  13-17：订阅/API付费，商业逻辑清晰，有竞争
  7-12 ：免费/广告/不清晰，或仅靠生态补贴
  0-6  ：开源无变现计划，或纯学术项目

④ 团队（0-15分）
  13-15：1990后，华人或顶级公司背景，AI+domain双栈
  9-12 ：背景合理但无特别亮点，或信息有限
  0-8  ：信息严重不足 / 创始人无AI背景 / 1990前且无特殊加持

⑤ 加减分（-10到+10）
  加：已有真实付费用户+4 / 开源>2k stars证明社区认可+2 / 顶级VC公开投资+3
      Claude Code生态/Proactive Agent/极小众结构机会+3
  减：老互联网公司AI化套壳-8 / 纯prompt拼装无壁垒-8 / 估值已>$2B-6
      信息严重不足难以评判-3 / 1990前创始人无AI背景-5

【分数校准】
- 85+分：极少数，Harvey/Sierra/Figure级别，强烈推荐跟进
- 75-84：值得深度了解，有明显Alpha信号
- 60-74：普通关注，需要更多信息验证
- 45-59：兴趣一般，可能是执行层面的机会但不是Alpha
- <45 ：不感兴趣，或信息不足

当你给出中间分数(68-76)时，必须在reason中解释为什么不更高或更低。

{fde_section}

{few_shot_section}

【输出JSON】score=ai_native+niche+business+team+bonus-penalty：
{{
  "score": 0,
  "ai_native": 0, "niche": 0, "business": 0, "team": 0, "bonus": 0, "penalty": 0,
  "fde_index": 0,
  "one_liner": "必须包含：项目名(英文) + 一句话说清做什么 + 最核心亮点 + Founder关键信息。例：'Harvey — AI法律助手，替律师做合同审查，$8B估值，Stanford法学+MIT CS背景团队'",
  "summary_zh": "【必须150字以上】全面介绍：①解决什么问题 ②产品如何工作（具体机制）③目标用户是谁 ④已有什么成果/数据证明",
  "biz_model_zh": "【必须80字以上】①具体收费方式 ②定价逻辑 ③为什么用户愿意付钱 ④与竞品的商业模式差异",
  "insight_zh": "【必须100字以上】Creekstone视角：①这个方向为什么有Alpha ②市场在哪里被低估 ③风险是什么 ④我们的投资论文如何适配",
  "score_narrative_zh": "【必须120字以上】逐维度解读：AI Native得X分因为... Niche得X分因为... 商业模式得X分因为... 团队得X分因为... 加减分因为...",
  "metrics_summary": "罗列所有已知数据：PH票数/GitHub stars(今日增量)/HN分数/OR增长/用户数/ARR等，无数据写'暂无公开数据'",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "plus": ["加分点（具体，不要泛泛而谈）"],
  "minus": ["减分点（具体，包括信息不足的减分）"],
  "reason": "核心评分理由：为什么是这个分数而不是更高或更低，60字以内"
}}"""


def _build_system_prompt(item: SignalItem, few_shots: list[dict]) -> str:
    track = item.track or "unknown"
    track_labels = {
        "A": "Track A — Agent基础框架 & 通用效率工具",
        "B": "Track B — 垂直Agent/FDE化",
        "C": "Track C — A2A网络",
        "Hardware": "Track Hardware — 硬件层 & 软硬结合",
        "Tech": "Track Tech — 纯技术突破 & 学术研究",
        "Multimodal": "Track Multimodal — 多模态应用",
        "Lifestyle": "Track Lifestyle — 情感陪伴 & 生活类",
        "unknown": "方向待定",
    }
    benchmark = TRACK_BENCHMARKS.get(track, TRACK_BENCHMARKS.get("A", ""))
    fde_section = FDE_SECTION if track == "B" else "(非Track B，fde_index填0)"

    fs_lines: list[str] = []
    if few_shots:
        fs_lines.append("【Gary已验证的历史参考样本】")
        for fs in few_shots[:4]:
            fs_lines.append(
                f"- {fs.get('title','')} → score:{fs.get('score',0)} "
                f"track:{fs.get('track','')} action:{fs.get('action','')} "
                f"reason:{fs.get('score_reason','')}"
            )
    few_shot_section = "\n".join(fs_lines)

    return BASE_SYSTEM_PROMPT.format(
        track_label=track_labels.get(track, track),
        track_benchmark=benchmark,
        fde_section=fde_section,
        few_shot_section=few_shot_section,
    )


def _build_user_msg(item: SignalItem) -> str:
    m = item.metrics
    # Build rich context for scoring
    signals = []
    if item.source == "producthunt":
        votes = m.get("votes", 0)
        signals.append(f"Product Hunt: {votes}票")
        if votes >= 300: signals.append("→ 高人气（>300票）")
        elif votes >= 100: signals.append("→ 中等人气（100-300票）")
        else: signals.append("→ 低人气（<100票）")
    elif item.source in ("github_trending", "github_events"):
        stars = m.get("stars", 0)
        spd = m.get("stars_today") or m.get("stars_per_day", 0)
        signals.append(f"GitHub: ⭐{stars:,} (+{spd}/今日)")
        if stars >= 5000: signals.append("→ 成熟项目")
        elif stars >= 1000: signals.append("→ 有社区认可")
        else: signals.append("→ 早期项目")
    elif item.source == "hackernews":
        pts = m.get("points", 0)
        cmts = m.get("comments", 0)
        signals.append(f"Hacker News: {pts}分 {cmts}条评论")
        if pts >= 200: signals.append("→ 高热度")
        elif pts >= 50: signals.append("→ 中等热度")
    elif item.source == "openrouter":
        wow = m.get("wow_pct", 0)
        signals.append(f"OpenRouter WoW增长: +{wow:.0f}%")
    
    signals_str = " | ".join(signals) if signals else "无指标数据"
    metrics_str = json.dumps(
        {k: v for k, v in m.items() if not isinstance(v, dict) and k not in ["raw"]},
        ensure_ascii=False
    )
    
    desc = item.description_en[:1200] if item.description_en else "（无描述）"
    
    return (
        f"产品名: {item.title}\n"
        f"来源: {item.source} | {item.url}\n"
        f"Track分类: {item.track} — {item.track_reason}\n"
        f"关键指标: {signals_str}\n"
        f"原始指标: {metrics_str[:300]}\n"
        f"\n产品描述（英文）:\n{desc}\n"
        f"\n【评分提醒】信息不足时宁可给低分，不要给中间分。"
        f"只有明确证据支持才给高分。"
    )


def _call_llm_with_retry(system: str, user_msg: str, model: str, timeout: float = 90) -> dict[str, Any]:
    """3 attempts with exponential backoff."""
    last_err = None
    for attempt in range(3):
        try:
            # S3 API call
            resp = requests.post(
                f"{config.LLM_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.LLM_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://creekstone.vc",
                    "X-Title": "CreekstoneRadarS3",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1800,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
            content = msg.get("content") or msg.get("reasoning") or ""
            if not content:
                raise ValueError("Empty response content")
            
            # 使用逐字符匹配法提取首个闭合的 {...}，完全防止 Extra Data 报错
            def extract_json(text: str) -> str:
                start = text.find('{')
                if start == -1: return ''
                count = 0
                for idx in range(start, len(text)):
                    if text[idx] == '{':
                        count += 1
                    elif text[idx] == '}':
                        count -= 1
                        if count == 0:
                            return text[start:idx+1]
                return ''
                
            clean_json = extract_json(content)
            if not clean_json:
                raise ValueError("No JSON block found in response")
                
            try:
                return json.loads(clean_json)
            except json.JSONDecodeError:
                # 最后的兜底
                m = re.search(r"\{.*\}", clean_json, re.S)
                if m:
                    return json.loads(m.group(0))
                raise
        except Exception as e:
            last_err = e
            if attempt < 2:
                wait = 2 ** attempt * 2
                log.warning("[S3] attempt %d failed: %s — retrying in %ds", attempt + 1, e, wait)
                time.sleep(wait)
    raise RuntimeError(f"S3 LLM failed after 3 attempts: {last_err}")


def _apply_result(item: SignalItem, result: dict) -> None:
    """Apply LLM result to item fields."""
    # Score
    try:
        item.score = round(float(result.get("score", 0)), 1)
    except (TypeError, ValueError):
        item.score = 0.0

    # Score breakdown
    item.score_breakdown = ScoreBreakdown(
        ai_native=int(result.get("ai_native", 0)),
        niche=int(result.get("niche", 0)),
        business=int(result.get("business", 0)),
        team=int(result.get("team", 0)),
        bonus=int(result.get("bonus", 0)),
        penalty=int(result.get("penalty", 0)),
        total=int(item.score),
        reason=str(result.get("reason", ""))[:200],
        plus=[str(p) for p in result.get("plus", [])[:5]],
        minus=[str(m) for m in result.get("minus", [])[:5]],
    )

    # Basic description
    item.description_zh = str(result.get("summary_zh", ""))[:500]
    raw_kw = result.get("keywords", [])
    item.keywords = [str(k).strip() for k in raw_kw if str(k).strip()][:8]

    # FDE
    if item.track == "B":
        try:
            item.fde_index = min(10, max(0, int(result.get("fde_index", 0))))
        except (TypeError, ValueError):
            item.fde_index = 0

    # Full profile (all items get at least the basics)
    item.full_profile = FullProfile(
        one_liner=str(result.get("one_liner", ""))[:100],
        overview_zh=str(result.get("summary_zh", ""))[:500],
        biz_model_zh=str(result.get("biz_model_zh", ""))[:300],
        insight_zh=str(result.get("insight_zh", ""))[:300],
        score_narrative_zh=str(result.get("score_narrative_zh", ""))[:400],
        metrics_summary=str(result.get("metrics_summary", ""))[:300],
        links=[item.url],
    )


def _score_one(args) -> tuple[int, dict]:
    """Score a single item. Returns (index, result_dict). Used for parallel execution."""
    idx, item, system, user_msg, model, timeout = args
    try:
        result = _call_llm_with_retry(system, user_msg, model=model, timeout=timeout)
        return idx, result
    except Exception as e:
        log.error("[S3] failed for '%s': %s", item.title[:40], e)
        return idx, {}


def run_s3(
    items: list[SignalItem],
    few_shot_loader=None,
    concurrency: int = 5,   # parallel Sonnet calls — safe for OpenRouter rate limits
) -> list[SignalItem]:
    """Score all items concurrently. Concurrency=5 cuts time from 55min→~12min for 82 items."""
    import concurrent.futures

    if not config.LLM_API_KEY:
        log.warning("[S3] no LLM key, skipping")
        return items

    model = os.getenv("S3_MODEL", "anthropic/claude-sonnet-4-5")
    timeout = max(90.0, config.LLM_TIMEOUT)
    few_shots = few_shot_loader() if few_shot_loader else []

    # Build all prompts upfront
    tasks = []
    for i, item in enumerate(items):
        system = _build_system_prompt(item, few_shots)
        user_msg = _build_user_msg(item)
        tasks.append((i, item, system, user_msg, model, timeout))

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(_score_one, task): task[0] for task in tasks}
        for future in concurrent.futures.as_completed(futures):
            idx, result = future.result()
            if result:
                _apply_result(items[idx], result)
            completed += 1
            if completed % 5 == 0 or completed == len(items):
                scored = [x for x in items[:completed+1] if x.score > 0]
                top_so_far = max((x.score for x in scored), default=0)
                log.info("[S3] %d/%d done — top so far: %.0f", completed, len(items), top_so_far)

    items.sort(key=lambda x: x.score, reverse=True)
    top = items[0].score if items else 0
    log.info("[S3] done — %d items scored, top: %.0f", len(items), top)
    return items
