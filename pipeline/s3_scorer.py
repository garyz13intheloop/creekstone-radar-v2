"""
S3 — Track-aware full scoring engine.
Replaces old scoring.py. Uses Track context + FDE benchmarks + few-shot injection.
Outputs: score, score_breakdown, fde_index, description_zh, keywords.
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
from models.item import SignalItem, ScoreBreakdown

log = logging.getLogger(__name__)

# ── Track-specific benchmark examples (injected into system prompt) ───────────
TRACK_BENCHMARKS = {
    "A": """Track A 基准参照（Agent框架）：
- LangChain score≈72：生态最大但商业化弱，被大量产品依赖
- OpenHands score≈78：开源coding agent，工具调用强，开发者社区活跃
- Exa score≈74：搜索API专为Agent设计，模型无关，采用率快速增长
- Cursor SDK score≈82：IDE级agent框架，开发者留存极高""",

    "B": """Track B 基准参照（垂直FDE）：
- Harvey($8B) score≈91：法律FDE，私有判例数据，律师停用即瘫痪，FDE指数9
- Abridge($5.3B) score≈88：医疗文档FDE，源头劫持医患对话，FDE指数8
- Sierra($10B) score≈90：B2B客服FDE，深度绑定企业知识库，FDE指数9
- EvenUp($2B) score≈83：法律理赔FDE，获赔金额提高30%+，FDE指数7
评分关键：同等其他条件下，FDE指数高的项目score应比FDE指数低的高5-8分""",

    "C": """Track C 基准参照（A2A网络）：
- HeyAgent score≈74：A2A协议早期探索，已有8个agent接入，网络效应初现
- AgentOps score≈70：agent运维监控，被多个agent采用，更像基础设施
硬件集成额外加分（+4）：结合物理世界执行器的agent协议价值显著高于纯软件""",
}

# ── System prompt template ────────────────────────────────────────────────────
BASE_SYSTEM_PROMPT = """你是 Creekstone Ventures 的投资评审助手。

【投资论文核心】
Creekstone 聚焦三个方向，当前产品属于 {track_label}：
{track_benchmark}

【评分维度（满分100分）】
一、AI Native & Agent 原生程度（0–30分）
- 用户行为是否自然生成高质量训练数据（数据飞轮）
- 是否存在 Online Learning / Self-improvement 闭环
- 是否从"概率性对话"走向"确定性工作流"（结果交付）
- Agent四要素：Reasoning / Memory / Tool-use / Planning

二、技术路径与 Niche 壁垒（0–25分）
- 是否选择主流不愿做的方向（非共识判断力）
- 是否构建原生私有数据飞轮（使用即生产数据）
- 是否有清晰可持续的场景护城河

三、商业模式与 Exit 形态（0–20分）
- 付费是否与真实价值强绑定（结果付费/效率分成）
- 是否具备被大厂收购/深度集成潜力
- 是否服务于1%高价值用户（停用即痛）

四、团队与进化能力（0–15分）
- 创始人1990年后优先；有华人背景加分
- 暴力学习+快速迭代能力；AI原生认知
- domain + AI 复合背景

五、加分项（+10）/ 减分项（-10）
加分：生态平台潜质+3 / 交互范式创新+3 / 重点方向+4（Claude Code产品化/Proactive Agent/极小众结构性机会）
减分：老互联网公司套壳-10 / 纯Prompt拼装-10 / 1990前创始人无亮点-5 / 估值>$1B-5

{fde_section}

{few_shot_section}

【输出格式】严格JSON，不要额外说明：
{{
  "score": 74,
  "ai_native": 22, "niche": 16, "business": 14, "team": 12, "bonus": 6, "penalty": 0,
  "fde_index": 0,
  "summary_zh": "2-3句中文介绍",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "plus": ["加分点1", "加分点2"],
  "minus": ["减分点1"],
  "reason": "不超过80字的中文评分理由"
}}
score必须等于ai_native+niche+business+team+bonus-penalty。
信息不足时允许低分，在reason中注明"信息不足"。"""

FDE_SECTION = """【FDE指数（Track B专用，0-10）】
- 0-3: 单点工具，未形成专家级覆盖
- 4-6: 在某子场景有深度，数据积累中
- 7-8: 覆盖领域>60%高频任务，有私有数据飞轮
- 9-10: FDE达成，停用即严重影响业务
评分时fde_index须与score高度相关：fde_index每+1约对应Niche维度+2分"""


def _build_prompt(item: SignalItem, few_shots: list[dict]) -> str:
    track = item.track or "unknown"
    track_labels = {
        "A": "Track A — Agent基础框架",
        "B": "Track B — 垂直Agent/FDE化",
        "C": "Track C — A2A网络",
        "unknown": "方向待定（请根据内容判断最接近的Track）",
    }
    benchmark = TRACK_BENCHMARKS.get(track, "")
    fde_section = FDE_SECTION if track == "B" else "(非Track B，fde_index填0)"

    # Few-shot injection
    fs_lines: list[str] = []
    if few_shots:
        fs_lines.append("【历史参考样本（Gary已验证）】")
        for fs in few_shots[:3]:
            fs_lines.append(
                f"- {fs.get('title','')} → score:{fs.get('score',0)} track:{fs.get('track','')} "
                f"action:{fs.get('action','')} reason:{fs.get('score_reason','')}"
            )
    few_shot_section = "\n".join(fs_lines)

    return BASE_SYSTEM_PROMPT.format(
        track_label=track_labels.get(track, track),
        track_benchmark=benchmark,
        fde_section=fde_section,
        few_shot_section=few_shot_section,
    )


def _call_llm(system: str, item: SignalItem) -> dict[str, Any]:
    user_msg = (
        f"产品: {item.title}\n"
        f"来源: {item.source}\n"
        f"Track分类: {item.track} ({item.track_reason})\n"
        f"描述(EN): {item.description_en[:800]}\n"
        f"指标: {json.dumps({k: v for k, v in item.metrics.items() if not isinstance(v, dict)}, ensure_ascii=False)}"
    )

    resp = requests.post(
        f"{config.LLM_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.LLM_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://creekstone.vc",
            "X-Title": "CreekstoneRadarS3",
        },
        json={
            "model": os.getenv("S3_MODEL", "anthropic/claude-haiku-4"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.2,
            "max_tokens": 600,
            "response_format": {"type": "json_object"},
        },
        timeout=config.LLM_TIMEOUT,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        return json.loads(m.group(0)) if m else {}


def _apply_result(item: SignalItem, result: dict) -> None:
    try:
        item.score = round(float(result.get("score", 0)), 1)
    except (TypeError, ValueError):
        item.score = 0.0

    breakdown = ScoreBreakdown(
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
    item.score_breakdown = breakdown

    item.description_zh = str(result.get("summary_zh", ""))[:400]
    raw_kw = result.get("keywords", [])
    item.keywords = [str(k).strip() for k in raw_kw if str(k).strip()][:8]

    if item.track == "B":
        try:
            item.fde_index = min(10, max(0, int(result.get("fde_index", 0))))
        except (TypeError, ValueError):
            item.fde_index = 0


def run_s3(
    items: list[SignalItem],
    few_shot_loader=None,   # callable() → list[dict]
) -> list[SignalItem]:
    """Score all items. Returns items with score/breakdown/fde_index filled."""
    import os
    if not config.LLM_API_KEY:
        log.warning("[S3] no LLM key, skipping scoring")
        return items

    few_shots = few_shot_loader() if few_shot_loader else []

    for i, item in enumerate(items):
        try:
            system = _build_prompt(item, few_shots)
            result = _call_llm(system, item)
            _apply_result(item, result)
            if (i + 1) % 5 == 0:
                log.info("[S3] scored %d/%d", i + 1, len(items))
            time.sleep(0.4)
        except Exception as e:
            log.error("[S3] failed for '%s': %s", item.title[:40], e)
            item.score = 0.0

    # Sort by score descending
    items.sort(key=lambda x: x.score, reverse=True)
    log.info("[S3] scored %d items, top score: %.1f", len(items), items[0].score if items else 0)
    return items
