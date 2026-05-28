"""
S2 — Expanded Track classification router.
7 Tracks: A (framework), B (vertical FDE), C (A2A),
          Hardware, Tech (research/papers), Multimodal, Lifestyle.
Single cheap LLM call (gemini-flash) per item.
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

SYSTEM_PROMPT = """你是 Creekstone Ventures 的产品分类助手。将产品分入以下7个Track之一。

【Track 定义与判断标准】

Track A — Agent框架 & 开发者基础设施
核心判断：开发者/工程师用它来「构建」AI Agent，而非直接「使用」AI完成业务。
特征：被其他产品作为依赖引入 / MCP工具/服务器 / LLM编排框架 / Agent内存/工具调用库
       IDE插件/coding assistant底层 / Agent评测/监控平台
代表：LangChain、CrewAI、Exa、OpenHands、Cursor SDK、AgentOps、任何"MCP Server"项目
⚠️ 注意：普通SaaS加了AI功能≠Track A；必须是供开发者构建agent的基础设施

Track B — 垂直Agent / FDE（Full Domain Expert）
核心判断：在某个具体业务场景「替代人工」完成完整工作流，越用越智能
特征：聚焦单一垂直领域 / 结果交付（不是对话）/ 积累私有领域数据 / 停用即影响业务
代表：Harvey(法律)、Abridge(医疗记录)、Sierra(B2B客服)、Glean(企业搜索)
FDE阶段: single_tool(0-3) → accumulating(4-6) → flywheel(7-8) → achieved(9-10)
⚠️ 注意：B2B SaaS+AI不一定是B；关键是「越用越懂这个领域」

Track C — A2A网络（Agent间协作协议）
核心判断：让多个Agent之间通信、协作、发现彼此的协议/网络层
特征：Agent注册/发现 / Agent间消息路由 / 跨Agent编排（非单一Agent内部）
代表：A2A协议实现、多Agent市场/目录
⚠️ 注意：单个Agent框架是A，只有Agent互联协议才是C

Track Hardware — 硬件与具身智能
核心判断：物理世界有硬件，或AI赋能芯片/算力
特征：机器人 / IoT / 具身智能 / AI芯片 / 边缘计算
代表：Figure AI、1X、Groq、Cerebras

Track Tech — 纯技术/算法/研究
核心判断：主要价值是技术突破本身，没有直接可用的商业产品
特征：arXiv论文 / 新算法 / 开源基础模型（无商业化）/ benchmark
代表：Attention变体论文、新的推理算法、纯学术dataset
⚠️ 注意：有商业产品的技术公司不是Tech；Llama/DeepSeek如果有API/应用→B或A

Track Multimodal — 多模态产品
核心判断：语音/视频/图像是产品的核心差异化，而不只是辅助功能
特征：语音合成/克隆 / 视频生成 / 图像生成平台 / 实时语音AI交互
代表：ElevenLabs、HeyGen、Runway、Suno、Kling
⚠️ 注意：加了语音功能的客服机器人→B；专门做语音合成的→Multimodal

Track Lifestyle — 生活/消费/陪伴
核心判断：面向普通消费者的日常生活场景，不是B2B也不是开发者工具
特征：情感陪伴 / 个人助理 / 健康/健身/学习/娱乐 / C端消费应用
代表：Character.AI、Pi、Replika、学习类App、个人财务AI

【分类决策树（顺序判断）】
1. 是arXiv/纯算法论文？→ Tech
2. 有实体硬件/芯片？→ Hardware
3. 多个Agent之间的通信协议/网络？→ C
4. 语音/视频/图像是核心产品？→ Multimodal
5. 面向C端个人生活场景？→ Lifestyle
6. 在某垂直业务领域替代人工完成工作流？→ B
7. 供开发者构建Agent的框架/工具/基础设施？→ A
8. 与AI/Agent完全无关 → relevant=false

【重要校验】
- GitHub上的工具项目：如果是MCP server/工具库→A；如果是某垂直应用→B；如果是学术代码→Tech
- HuggingFace模型：基础模型无商业化→Tech；有具体应用场景→对应Track
- Product Hunt产品：认真看tagline，不要因为"AI"就归入A

输出严格JSON，无额外说明：
{
  "relevant": true,
  "track": "A",
  "track_reason": "一句话不超过20字，说明归入该Track的核心理由",
  "confidence": "high",
  "fde_stage": ""
}
confidence: high=特征明显 / medium=基本符合 / low=不确定或borderline
fde_stage: 仅Track B填写，其他为""
relevant=false时其他字段填空"""


def _call_llm(item: SignalItem) -> dict[str, Any]:
    user_msg = (
        f"标题: {item.title}\n"
        f"来源: {item.source}\n"
        f"描述: {item.description_en[:600]}\n"
        f"指标: {_fmt_metrics(item)}"
    )

    for attempt in range(3):
        try:
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
                    "max_tokens": 150,
                },
                timeout=30,
            )
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
            content = msg.get("content") or msg.get("reasoning") or ""
            
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
            return json.loads(clean_json)
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("[S2] parse error attempt %d: %s", attempt + 1, e)
            if attempt == 2:
                return {}
        except Exception as e:
            log.warning("[S2] request error attempt %d: %s", attempt + 1, e)
            if attempt == 2:
                return {}
            time.sleep(2 ** attempt)
    return {}


def _fmt_metrics(item: SignalItem) -> str:
    m = item.metrics
    src = item.source
    if src == "producthunt":
        return f"PH votes:{m.get('votes', 0)}"
    elif src in ("github_trending", "github_events"):
        return f"Stars:{m.get('stars', 0)} today:{m.get('stars_today', m.get('stars_per_day', 0))}"
    elif src == "openrouter":
        return f"Tokens:{m.get('tokens_week','')} WoW:+{m.get('wow_pct',0):.0f}%"
    elif src == "x_twitter":
        return f"Likes:{m.get('likes',0)} Bookmarks:{m.get('bookmarks',0)}"
    elif src == "hackernews":
        return f"HN points:{m.get('points',0)}"
    elif src == "arxiv":
        return "arXiv paper"
    return "n/a"


VALID_TRACKS: dict[str, Track] = {
    "A": "A", "B": "B", "C": "C",
    "HARDWARE": "Hardware", "Hardware": "Hardware",
    "TECH": "Tech", "Tech": "Tech",
    "MULTIMODAL": "Multimodal", "Multimodal": "Multimodal",
    "LIFESTYLE": "Lifestyle", "Lifestyle": "Lifestyle",
}


def _apply_result(item: SignalItem, result: dict) -> bool:
    if not result.get("relevant", True):
        return False

    raw_track = str(result.get("track", "")).strip()
    item.track = VALID_TRACKS.get(raw_track, VALID_TRACKS.get(raw_track.upper(), "unknown"))
    item.track_reason = str(result.get("track_reason", ""))[:100]
    item.track_confidence = result.get("confidence", "low")

    if item.track == "B":
        item.fde_stage = result.get("fde_stage", "single_tool") or "single_tool"

    # arXiv always → Tech
    if item.source == "arxiv" and item.track == "unknown":
        item.track = "Tech"
        item.track_reason = "arXiv论文，归入技术突破Track"
        item.track_confidence = "high"

    return True


def run_s2(
    items: list[SignalItem],
    skip_if_no_key: bool = True,
) -> tuple[list[SignalItem], int]:
    """Returns (passed_items, dropped_count)."""
    if not config.LLM_API_KEY:
        if skip_if_no_key:
            log.warning("[S2] no LLM key — all items pass with track=unknown")
            for item in items:
                item.track = "unknown"
                item.track_confidence = "low"
                if item.source == "arxiv":
                    item.track = "Tech"
            return items, 0
        raise RuntimeError("LLM_API_KEY required for S2")

    passed: list[SignalItem] = []
    dropped = 0

    for item in items:
        try:
            result = _call_llm(item)
            if not result:
                item.track = "unknown"
                item.track_confidence = "low"
                passed.append(item)
                continue
            keep = _apply_result(item, result)
            if keep:
                passed.append(item)
            else:
                dropped += 1
                log.debug("[S2] dropped irrelevant: %s", item.title[:40])
        except Exception as e:
            log.warning("[S2] failed for '%s': %s — keeping", item.title[:40], e)
            item.track = "unknown"
            item.track_confidence = "low"
            passed.append(item)
        time.sleep(0.2)

    log.info("[S2] %d → %d (dropped %d)", len(items), len(passed), dropped)
    return passed, dropped
